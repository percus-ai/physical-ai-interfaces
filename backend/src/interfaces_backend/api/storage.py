"""Storage API router for datasets/models (DB-backed)."""

import asyncio
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from huggingface_hub import HfApi, snapshot_download, upload_folder
from pydantic import ValidationError

from interfaces_backend.models.storage import (
    ArchiveListResponse,
    ArchiveBulkRequest,
    ArchiveBulkResponse,
    ArchiveResponse,
    DatasetMergeRequest,
    DatasetMergeResponse,
    DatasetInfo,
    DatasetListResponse,
    EnvironmentCreateRequest,
    EnvironmentInfo,
    EnvironmentListResponse,
    HuggingFaceDatasetImportRequest,
    HuggingFaceExportRequest,
    HuggingFaceModelImportRequest,
    HuggingFaceTransferResponse,
    ModelInfo,
    ModelListResponse,
    StorageUsageResponse,
)
from percus_ai.db import get_supabase_client, upsert_with_owner
from percus_ai.storage.hash import compute_directory_hash, compute_directory_size
from percus_ai.storage.hub import download_model, ensure_hf_token, get_local_model_info, upload_model
from percus_ai.storage.naming import validate_dataset_name
from percus_ai.storage.paths import get_datasets_dir, get_models_dir
from percus_ai.storage.r2_db_sync import R2DBSyncService
from lerobot.datasets.aggregate import aggregate_datasets
from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/storage", tags=["storage"])
_executor = ThreadPoolExecutor(max_workers=1)


def _dataset_is_local(dataset_id: str) -> bool:
    dataset_path = get_datasets_dir() / dataset_id
    return dataset_path.exists()


def _model_is_local(model_id: str) -> bool:
    model_path = get_models_dir() / model_id
    return model_path.exists()


def _delete_local_dataset(dataset_id: str) -> None:
    dataset_path = get_datasets_dir() / dataset_id
    if dataset_path.exists():
        shutil.rmtree(dataset_path)


def _delete_local_model(model_id: str) -> None:
    model_path = get_models_dir() / model_id
    if model_path.exists():
        shutil.rmtree(model_path)


def _detach_models_from_dataset(dataset_id: str) -> None:
    client = get_supabase_client()
    client.table("models").update({"dataset_id": None}).eq("dataset_id", dataset_id).execute()


def _dataset_row_to_info(row: dict) -> DatasetInfo:
    return DatasetInfo(
        id=row.get("id"),
        name=row.get("name") or row.get("id"),
        project_id=row.get("project_id"),
        environment_id=row.get("environment_id"),
        source=row.get("source") or "r2",
        status=row.get("status") or "active",
        dataset_type=row.get("dataset_type") or "recorded",
        episode_count=row.get("episode_count") or 0,
        size_bytes=row.get("size_bytes") or 0,
        is_local=_dataset_is_local(row.get("id")),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _environment_row_to_info(row: dict) -> EnvironmentInfo:
    return EnvironmentInfo(
        id=row.get("id"),
        name=row.get("name") or row.get("id"),
        description=row.get("description"),
        camera_count=row.get("camera_count"),
        camera_details=row.get("camera_details"),
        image_files=row.get("image_files"),
        notes=row.get("notes"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _model_row_to_info(row: dict) -> ModelInfo:
    return ModelInfo(
        id=row.get("id"),
        name=row.get("name") or row.get("id"),
        project_id=row.get("project_id"),
        dataset_id=row.get("dataset_id"),
        policy_type=row.get("policy_type"),
        training_steps=row.get("training_steps"),
        batch_size=row.get("batch_size"),
        size_bytes=row.get("size_bytes") or 0,
        source=row.get("source") or "r2",
        status=row.get("status") or "active",
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


@router.get("/environments", response_model=EnvironmentListResponse)
async def list_environments():
    """List environments from DB."""
    client = get_supabase_client()
    rows = client.table("environments").select("*").execute().data or []
    environments = [_environment_row_to_info(row) for row in rows]
    return EnvironmentListResponse(environments=environments, total=len(environments))


@router.post("/environments", response_model=EnvironmentInfo)
async def create_environment(request: EnvironmentCreateRequest):
    """Create environment in DB."""
    record = {
        "name": request.name,
        "description": request.description,
        "camera_count": request.camera_count,
        "camera_details": request.camera_details,
        "image_files": request.image_files,
        "notes": request.notes,
    }
    upsert_with_owner("environments", "name", record)
    client = get_supabase_client()
    rows = (
        client.table("environments")
        .select("*")
        .eq("name", request.name)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(status_code=500, detail="Failed to create environment")
    return _environment_row_to_info(rows[0])


@router.get("/environments/{environment_id}", response_model=EnvironmentInfo)
async def get_environment(environment_id: str):
    """Get environment details from DB."""
    client = get_supabase_client()
    rows = (
        client.table("environments")
        .select("*")
        .eq("id", environment_id)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Environment not found: {environment_id}")
    return _environment_row_to_info(rows[0])


@router.get("/datasets", response_model=DatasetListResponse)
async def list_datasets(
    include_archived: bool = Query(False, description="Include archived datasets"),
    project_id: Optional[str] = Query(None, description="Filter by project"),
):
    """List datasets from DB."""
    client = get_supabase_client()
    query = client.table("datasets").select("*")
    if not include_archived:
        query = query.eq("status", "active")
    if project_id:
        query = query.eq("project_id", project_id)
    rows = query.execute().data or []

    datasets = [_dataset_row_to_info(row) for row in rows]
    return DatasetListResponse(datasets=datasets, total=len(datasets))


def _merge_datasets(
    request: DatasetMergeRequest,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> DatasetMergeResponse:
    def report(message: dict) -> None:
        if progress_callback:
            progress_callback(message)

    source_dataset_ids = list(dict.fromkeys(request.source_dataset_ids))
    if len(source_dataset_ids) < 2:
        raise HTTPException(status_code=400, detail="At least two source datasets are required")

    is_valid, errors = validate_dataset_name(request.dataset_name)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid dataset name: {'; '.join(errors)}")

    merged_dataset_id = f"{request.project_id}/{request.dataset_name}"
    client = get_supabase_client()
    existing = client.table("datasets").select("id").eq("id", merged_dataset_id).execute().data or []
    if existing:
        raise HTTPException(status_code=409, detail=f"Dataset already exists: {merged_dataset_id}")

    report({"type": "start", "step": "validate", "message": "Validating datasets"})
    source_rows = []
    for dataset_id in source_dataset_ids:
        rows = client.table("datasets").select("*").eq("id", dataset_id).execute().data or []
        if not rows:
            raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
        row = rows[0]
        if row.get("status") != "active":
            raise HTTPException(status_code=400, detail=f"Dataset is not active: {dataset_id}")
        if row.get("project_id") != request.project_id:
            raise HTTPException(
                status_code=400,
                detail=f"Project mismatch for dataset {dataset_id}: {row.get('project_id')}",
            )
        source_rows.append(row)
    report({"type": "step_complete", "step": "validate", "message": "Validation complete"})

    environment_ids = {row.get("environment_id") for row in source_rows if row.get("environment_id")}
    if len(environment_ids) > 1:
        raise HTTPException(status_code=400, detail="Environment mismatch across source datasets")
    environment_id = next(iter(environment_ids), None)

    report({"type": "start", "step": "download", "message": "Ensuring local datasets"})
    sync_service = R2DBSyncService()
    for dataset_id in source_dataset_ids:
        report({"type": "progress", "step": "download", "dataset_id": dataset_id})
        result = sync_service.ensure_dataset_local(dataset_id, auto_download=True)
        if not result.success:
            raise HTTPException(status_code=500, detail=f"Dataset download failed: {result.message}")
    report({"type": "step_complete", "step": "download", "message": "Local datasets ready"})

    datasets_dir = get_datasets_dir()
    merged_root = datasets_dir / merged_dataset_id
    if merged_root.exists():
        raise HTTPException(status_code=409, detail=f"Local dataset already exists: {merged_dataset_id}")

    report({"type": "start", "step": "aggregate", "message": "Aggregating datasets"})
    roots = [datasets_dir / dataset_id for dataset_id in source_dataset_ids]
    try:
        aggregate_datasets(
            repo_ids=source_dataset_ids,
            aggr_repo_id=merged_dataset_id,
            roots=roots,
            aggr_root=merged_root,
        )
    except Exception as e:
        if merged_root.exists():
            shutil.rmtree(merged_root)
        raise HTTPException(status_code=500, detail=f"Dataset merge failed: {e}") from e
    report({"type": "step_complete", "step": "aggregate", "message": "Aggregation complete"})

    metadata = LeRobotDatasetMetadata(merged_dataset_id, root=merged_root)
    episode_count = metadata.total_episodes
    size_bytes = compute_directory_size(merged_root)
    content_hash = compute_directory_hash(merged_root, use_content=True)

    def upload_progress(message: dict) -> None:
        msg_type = message.get("type")
        if msg_type == "error":
            report({"type": "error", "error": message.get("error")})
            return
        type_map = {
            "start": "upload_start",
            "uploading": "uploading",
            "progress": "upload_progress",
            "uploaded": "upload_file_complete",
            "complete": "upload_complete",
        }
        report({**message, "type": type_map.get(msg_type, msg_type), "step": "upload"})

    report({"type": "start", "step": "upload", "message": "Uploading merged dataset"})
    ok, error = sync_service.upload_dataset_with_progress(merged_dataset_id, upload_progress)
    if not ok:
        shutil.rmtree(merged_root)
        raise HTTPException(status_code=500, detail=f"R2 upload failed: {error}")
    report({"type": "step_complete", "step": "upload", "message": "Upload complete"})

    payload = {
        "id": merged_dataset_id,
        "project_id": request.project_id,
        "name": request.dataset_name,
        "environment_id": environment_id,
        "episode_count": episode_count,
        "dataset_type": "merged",
        "source": "r2",
        "status": "active",
        "size_bytes": size_bytes,
        "content_hash": content_hash,
    }
    upsert_with_owner("datasets", "id", payload)

    return DatasetMergeResponse(
        success=True,
        dataset_id=merged_dataset_id,
        message="Dataset merged",
        size_bytes=size_bytes,
        episode_count=episode_count,
    )


@router.post("/datasets/merge", response_model=DatasetMergeResponse)
async def merge_datasets(request: DatasetMergeRequest):
    """Merge multiple datasets into a new dataset."""
    return _merge_datasets(request)


@router.websocket("/ws/merge")
async def websocket_merge_datasets(websocket: WebSocket):
    """WebSocket endpoint for dataset merge with progress updates."""
    await websocket.accept()

    try:
        data = await websocket.receive_json()
        request = DatasetMergeRequest(**data)
    except ValidationError as e:
        await websocket.send_json({"type": "error", "error": str(e)})
        await websocket.close()
        return
    except Exception:
        await websocket.send_json({"type": "error", "error": "Invalid request"})
        await websocket.close()
        return

    progress_queue: asyncio.Queue = asyncio.Queue()
    main_loop = asyncio.get_running_loop()

    def progress_callback(progress: dict) -> None:
        asyncio.run_coroutine_threadsafe(progress_queue.put(progress), main_loop)

    async def run_merge() -> None:
        try:
            result = await main_loop.run_in_executor(_executor, lambda: _merge_datasets(request, progress_callback))
            await progress_queue.put({"type": "complete", **result.model_dump()})
        except HTTPException as e:
            await progress_queue.put({"type": "error", "error": e.detail})
        except Exception as e:
            await progress_queue.put({"type": "error", "error": str(e)})

    merge_task = asyncio.create_task(run_merge())

    try:
        while True:
            try:
                progress = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                await websocket.send_json(progress)
                if progress.get("type") in ("complete", "error"):
                    break
            except asyncio.TimeoutError:
                if merge_task.done():
                    break
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected during dataset merge")
    except Exception as e:
        logger.error(f"WebSocket merge error: {e}")
    finally:
        if not merge_task.done():
            merge_task.cancel()
        await websocket.close()


@router.get("/datasets/{dataset_id:path}", response_model=DatasetInfo)
async def get_dataset(dataset_id: str):
    """Get dataset details from DB."""
    client = get_supabase_client()
    rows = client.table("datasets").select("*").eq("id", dataset_id).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    return _dataset_row_to_info(rows[0])


@router.delete("/datasets/{dataset_id:path}", response_model=ArchiveResponse)
async def archive_dataset(dataset_id: str):
    """Archive (soft delete) a dataset."""
    client = get_supabase_client()
    existing = client.table("datasets").select("id").eq("id", dataset_id).execute().data or []
    if not existing:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    client.table("datasets").update({"status": "archived"}).eq("id", dataset_id).execute()
    return ArchiveResponse(id=dataset_id, success=True, message="Dataset archived", status="archived")


@router.post("/datasets/{dataset_id:path}/restore", response_model=ArchiveResponse)
async def restore_dataset(dataset_id: str):
    """Restore dataset from archive."""
    client = get_supabase_client()
    existing = client.table("datasets").select("id").eq("id", dataset_id).execute().data or []
    if not existing:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    client.table("datasets").update({"status": "active"}).eq("id", dataset_id).execute()
    return ArchiveResponse(id=dataset_id, success=True, message="Dataset restored", status="active")


@router.get("/models", response_model=ModelListResponse)
async def list_models(
    include_archived: bool = Query(False, description="Include archived models"),
    project_id: Optional[str] = Query(None, description="Filter by project"),
):
    """List models from DB."""
    client = get_supabase_client()
    query = client.table("models").select("*")
    if not include_archived:
        query = query.eq("status", "active")
    if project_id:
        query = query.eq("project_id", project_id)
    rows = query.execute().data or []
    models = [_model_row_to_info(row) for row in rows]
    return ModelListResponse(models=models, total=len(models))


@router.get("/models/{model_id}", response_model=ModelInfo)
async def get_model(model_id: str):
    """Get model details from DB."""
    client = get_supabase_client()
    rows = client.table("models").select("*").eq("id", model_id).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    return _model_row_to_info(rows[0])


@router.delete("/models/{model_id}", response_model=ArchiveResponse)
async def archive_model(model_id: str):
    """Archive (soft delete) a model."""
    client = get_supabase_client()
    existing = client.table("models").select("id").eq("id", model_id).execute().data or []
    if not existing:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    client.table("models").update({"status": "archived"}).eq("id", model_id).execute()
    return ArchiveResponse(id=model_id, success=True, message="Model archived", status="archived")


@router.post("/models/{model_id}/restore", response_model=ArchiveResponse)
async def restore_model(model_id: str):
    """Restore model from archive."""
    client = get_supabase_client()
    existing = client.table("models").select("id").eq("id", model_id).execute().data or []
    if not existing:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    client.table("models").update({"status": "active"}).eq("id", model_id).execute()
    return ArchiveResponse(id=model_id, success=True, message="Model restored", status="active")


@router.get("/usage", response_model=StorageUsageResponse)
async def get_storage_usage():
    """Get storage usage statistics from DB."""
    client = get_supabase_client()
    datasets = client.table("datasets").select("size_bytes,status").execute().data or []
    models = client.table("models").select("size_bytes,status").execute().data or []

    datasets_size = sum(d.get("size_bytes") or 0 for d in datasets if d.get("status") == "active")
    models_size = sum(m.get("size_bytes") or 0 for m in models if m.get("status") == "active")
    archive_size = sum(d.get("size_bytes") or 0 for d in datasets if d.get("status") == "archived")
    archive_size += sum(m.get("size_bytes") or 0 for m in models if m.get("status") == "archived")

    return StorageUsageResponse(
        datasets_count=sum(1 for d in datasets if d.get("status") == "active"),
        datasets_size_bytes=datasets_size,
        models_count=sum(1 for m in models if m.get("status") == "active"),
        models_size_bytes=models_size,
        archive_count=sum(1 for d in datasets if d.get("status") == "archived")
        + sum(1 for m in models if m.get("status") == "archived"),
        archive_size_bytes=archive_size,
        total_size_bytes=datasets_size + models_size + archive_size,
    )


@router.get("/archive", response_model=ArchiveListResponse)
async def list_archived():
    """List archived datasets and models."""
    client = get_supabase_client()
    datasets = client.table("datasets").select("*").eq("status", "archived").execute().data or []
    models = client.table("models").select("*").eq("status", "archived").execute().data or []
    dataset_infos = [_dataset_row_to_info(d) for d in datasets]
    model_infos = [_model_row_to_info(m) for m in models]
    return ArchiveListResponse(
        datasets=dataset_infos,
        models=model_infos,
        total=len(dataset_infos) + len(model_infos),
    )


@router.delete("/archive/datasets/{dataset_id:path}", response_model=ArchiveResponse)
async def delete_archived_dataset(dataset_id: str):
    """Permanently delete an archived dataset."""
    client = get_supabase_client()
    existing = client.table("datasets").select("id,status").eq("id", dataset_id).execute().data or []
    if not existing:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    if existing[0].get("status") != "archived":
        raise HTTPException(status_code=400, detail="Dataset is not archived")

    _detach_models_from_dataset(dataset_id)
    sync_service = R2DBSyncService()
    sync_service.delete_dataset_remote(dataset_id)
    _delete_local_dataset(dataset_id)
    client.table("datasets").delete().eq("id", dataset_id).execute()
    return ArchiveResponse(id=dataset_id, success=True, message="Dataset deleted", status="deleted")


@router.delete("/archive/models/{model_id}", response_model=ArchiveResponse)
async def delete_archived_model(model_id: str):
    """Permanently delete an archived model."""
    client = get_supabase_client()
    existing = client.table("models").select("id,status").eq("id", model_id).execute().data or []
    if not existing:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    if existing[0].get("status") != "archived":
        raise HTTPException(status_code=400, detail="Model is not archived")

    sync_service = R2DBSyncService()
    sync_service.delete_model_remote(model_id)
    _delete_local_model(model_id)
    client.table("training_jobs").update({"model_id": None}).eq("model_id", model_id).execute()
    client.table("models").delete().eq("id", model_id).execute()
    return ArchiveResponse(id=model_id, success=True, message="Model deleted", status="deleted")


@router.post("/archive/restore", response_model=ArchiveBulkResponse)
async def restore_archived_items(request: ArchiveBulkRequest):
    """Bulk restore archived datasets/models."""
    client = get_supabase_client()
    restored: list[str] = []
    errors: list[str] = []

    for dataset_id in request.dataset_ids:
        existing = client.table("datasets").select("id,status").eq("id", dataset_id).execute().data or []
        if not existing:
            errors.append(f"Dataset not found: {dataset_id}")
            continue
        client.table("datasets").update({"status": "active"}).eq("id", dataset_id).execute()
        restored.append(dataset_id)

    for model_id in request.model_ids:
        existing = client.table("models").select("id,status").eq("id", model_id).execute().data or []
        if not existing:
            errors.append(f"Model not found: {model_id}")
            continue
        client.table("models").update({"status": "active"}).eq("id", model_id).execute()
        restored.append(model_id)

    return ArchiveBulkResponse(
        success=len(errors) == 0,
        restored=restored,
        deleted=[],
        errors=errors,
    )


@router.post("/archive/delete", response_model=ArchiveBulkResponse)
async def delete_archived_items(request: ArchiveBulkRequest):
    """Bulk delete archived datasets/models."""
    client = get_supabase_client()
    sync_service = R2DBSyncService()
    deleted: list[str] = []
    errors: list[str] = []

    for dataset_id in request.dataset_ids:
        existing = client.table("datasets").select("id,status").eq("id", dataset_id).execute().data or []
        if not existing:
            errors.append(f"Dataset not found: {dataset_id}")
            continue
        if existing[0].get("status") != "archived":
            errors.append(f"Dataset is not archived: {dataset_id}")
            continue
        _detach_models_from_dataset(dataset_id)
        sync_service.delete_dataset_remote(dataset_id)
        _delete_local_dataset(dataset_id)
        client.table("datasets").delete().eq("id", dataset_id).execute()
        deleted.append(dataset_id)

    for model_id in request.model_ids:
        existing = client.table("models").select("id,status").eq("id", model_id).execute().data or []
        if not existing:
            errors.append(f"Model not found: {model_id}")
            continue
        if existing[0].get("status") != "archived":
            errors.append(f"Model is not archived: {model_id}")
            continue
        sync_service.delete_model_remote(model_id)
        _delete_local_model(model_id)
        client.table("training_jobs").update({"model_id": None}).eq("model_id", model_id).execute()
        client.table("models").delete().eq("id", model_id).execute()
        deleted.append(model_id)

    return ArchiveBulkResponse(
        success=len(errors) == 0,
        restored=[],
        deleted=deleted,
        errors=errors,
    )


def _upsert_dataset_from_hf(
    dataset_id: str,
    project_id: str,
    name: str,
) -> None:
    payload = {
        "id": dataset_id,
        "project_id": project_id,
        "name": name,
        "dataset_type": "huggingface",
        "source": "huggingface",
        "status": "active",
    }
    upsert_with_owner("datasets", "id", payload)


def _upsert_model_from_hf(
    model_id: str,
    project_id: str,
    name: str,
    dataset_id: Optional[str],
    policy_type: Optional[str],
) -> None:
    payload = {
        "id": model_id,
        "project_id": project_id,
        "name": name,
        "dataset_id": dataset_id,
        "policy_type": policy_type,
        "model_type": "huggingface",
        "source": "huggingface",
        "status": "active",
    }
    upsert_with_owner("models", "id", payload)


def _report_upload_progress(
    message: dict,
    report: Optional[Callable[[dict], None]],
) -> None:
    if report is None:
        return
    msg_type = message.get("type")
    if not msg_type:
        return
    type_map = {
        "start": "upload_start",
        "uploading": "uploading",
        "progress": "upload_progress",
        "uploaded": "upload_file_complete",
        "complete": "upload_complete",
    }
    report({**message, "type": type_map.get(msg_type, msg_type), "step": "upload"})


def _import_dataset_from_huggingface(
    request: HuggingFaceDatasetImportRequest,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> HuggingFaceTransferResponse:
    if not ensure_hf_token():
        raise HTTPException(status_code=400, detail="HF_TOKEN is required")
    dataset_id = request.dataset_id
    local_path = get_datasets_dir() / dataset_id
    if local_path.exists():
        if request.force:
            shutil.rmtree(local_path)
        else:
            raise HTTPException(status_code=409, detail=f"Dataset already exists: {dataset_id}")

    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "hf_download",
            "message": f"Downloading {request.repo_id}",
        })
    local_path.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=request.repo_id,
        repo_type="dataset",
        local_dir=str(local_path),
        local_dir_use_symlinks=False,
    )
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "hf_download",
            "message": "Download complete",
        })

    name = request.name or dataset_id.split("/")[-1]
    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "db_upsert",
            "message": "Registering dataset",
        })
    _upsert_dataset_from_hf(dataset_id, request.project_id, name)
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "db_upsert",
            "message": "Dataset registered",
        })

    sync_service = R2DBSyncService()
    ok, error = sync_service.upload_dataset_with_progress(
        dataset_id,
        lambda message: _report_upload_progress(message, progress_callback),
    )
    if not ok:
        raise HTTPException(status_code=500, detail=f"R2 upload failed: {error}")

    return HuggingFaceTransferResponse(
        success=True,
        message="Dataset imported from HuggingFace",
        item_id=dataset_id,
        repo_url=f"https://huggingface.co/datasets/{request.repo_id}",
    )


def _import_model_from_huggingface(
    request: HuggingFaceModelImportRequest,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> HuggingFaceTransferResponse:
    if not ensure_hf_token():
        raise HTTPException(status_code=400, detail="HF_TOKEN is required")
    model_id = request.model_id
    local_path = get_models_dir() / model_id
    if local_path.exists():
        if request.force:
            shutil.rmtree(local_path)
        else:
            raise HTTPException(status_code=409, detail=f"Model already exists: {model_id}")

    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "hf_download",
            "message": f"Downloading {request.repo_id}",
        })
    download_model(repo_id=request.repo_id, output_dir=local_path, force=request.force)
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "hf_download",
            "message": "Download complete",
        })
    local_info = get_local_model_info(local_path)
    policy_type = local_info.policy_type if local_info else None
    name = request.name or model_id

    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "db_upsert",
            "message": "Registering model",
        })
    _upsert_model_from_hf(model_id, request.project_id, name, request.dataset_id, policy_type)
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "db_upsert",
            "message": "Model registered",
        })

    sync_service = R2DBSyncService()
    result = sync_service.upload_model(model_id)
    if not result.success:
        raise HTTPException(status_code=500, detail=f"R2 upload failed: {result.message}")

    return HuggingFaceTransferResponse(
        success=True,
        message="Model imported from HuggingFace",
        item_id=model_id,
        repo_url=f"https://huggingface.co/{request.repo_id}",
    )


def _export_dataset_to_huggingface(
    dataset_id: str,
    request: HuggingFaceExportRequest,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> HuggingFaceTransferResponse:
    if not ensure_hf_token():
        raise HTTPException(status_code=400, detail="HF_TOKEN is required")
    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "ensure_local",
            "message": "Checking local dataset cache",
        })
    sync_service = R2DBSyncService()
    result = sync_service.ensure_dataset_local(dataset_id, auto_download=True)
    if not result.success:
        raise HTTPException(status_code=500, detail=f"Dataset download failed: {result.message}")
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "ensure_local",
            "message": result.message,
        })

    local_path = get_datasets_dir() / dataset_id
    if not local_path.exists():
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "hf_upload",
            "message": f"Uploading to {request.repo_id}",
        })
    api = HfApi()
    api.create_repo(
        repo_id=request.repo_id,
        repo_type="dataset",
        exist_ok=True,
        private=request.private,
    )
    commit_message = request.commit_message or f"Upload dataset: {dataset_id}"
    upload_folder(
        folder_path=str(local_path),
        repo_id=request.repo_id,
        repo_type="dataset",
        commit_message=commit_message,
    )
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "hf_upload",
            "message": "Upload complete",
        })

    return HuggingFaceTransferResponse(
        success=True,
        message="Dataset exported to HuggingFace",
        item_id=dataset_id,
        repo_url=f"https://huggingface.co/datasets/{request.repo_id}",
    )


def _export_model_to_huggingface(
    model_id: str,
    request: HuggingFaceExportRequest,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> HuggingFaceTransferResponse:
    if not ensure_hf_token():
        raise HTTPException(status_code=400, detail="HF_TOKEN is required")
    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "ensure_local",
            "message": "Checking local model cache",
        })
    sync_service = R2DBSyncService()
    result = sync_service.ensure_model_local(model_id, auto_download=True)
    if not result.success:
        raise HTTPException(status_code=500, detail=f"Model download failed: {result.message}")
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "ensure_local",
            "message": result.message,
        })

    local_path = get_models_dir() / model_id
    if not local_path.exists():
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")

    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "hf_upload",
            "message": f"Uploading to {request.repo_id}",
        })
    repo_url = upload_model(
        local_path=local_path,
        repo_id=request.repo_id,
        private=request.private,
        commit_message=request.commit_message,
    )
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "hf_upload",
            "message": "Upload complete",
        })

    return HuggingFaceTransferResponse(
        success=True,
        message="Model exported to HuggingFace",
        item_id=model_id,
        repo_url=repo_url,
    )


@router.post("/huggingface/datasets/import", response_model=HuggingFaceTransferResponse)
async def import_dataset_from_huggingface(request: HuggingFaceDatasetImportRequest):
    return _import_dataset_from_huggingface(request)


@router.post("/huggingface/models/import", response_model=HuggingFaceTransferResponse)
async def import_model_from_huggingface(request: HuggingFaceModelImportRequest):
    return _import_model_from_huggingface(request)


@router.post("/huggingface/datasets/{dataset_id:path}/export", response_model=HuggingFaceTransferResponse)
async def export_dataset_to_huggingface(dataset_id: str, request: HuggingFaceExportRequest):
    return _export_dataset_to_huggingface(dataset_id, request)


@router.post("/huggingface/models/{model_id}/export", response_model=HuggingFaceTransferResponse)
async def export_model_to_huggingface(model_id: str, request: HuggingFaceExportRequest):
    return _export_model_to_huggingface(model_id, request)


@router.websocket("/ws/huggingface/datasets/import")
async def websocket_import_dataset_from_huggingface(websocket: WebSocket):
    await websocket.accept()

    try:
        data = await websocket.receive_json()
        request = HuggingFaceDatasetImportRequest(**data)
    except ValidationError as e:
        await websocket.send_json({"type": "error", "error": str(e)})
        await websocket.close()
        return
    except Exception:
        await websocket.send_json({"type": "error", "error": "Invalid request"})
        await websocket.close()
        return

    progress_queue: asyncio.Queue = asyncio.Queue()
    main_loop = asyncio.get_running_loop()

    def progress_callback(progress: dict) -> None:
        asyncio.run_coroutine_threadsafe(progress_queue.put(progress), main_loop)

    async def run_import() -> None:
        try:
            result = await main_loop.run_in_executor(
                _executor,
                lambda: _import_dataset_from_huggingface(request, progress_callback),
            )
            await progress_queue.put({"type": "complete", **result.model_dump()})
        except HTTPException as e:
            await progress_queue.put({"type": "error", "error": e.detail})
        except Exception as e:
            await progress_queue.put({"type": "error", "error": str(e)})

    import_task = asyncio.create_task(run_import())

    try:
        while True:
            try:
                progress = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                await websocket.send_json(progress)
                if progress.get("type") in ("complete", "error"):
                    break
            except asyncio.TimeoutError:
                if import_task.done():
                    break
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected during HF dataset import")
    except Exception as e:
        logger.error(f"WebSocket HF dataset import error: {e}")
    finally:
        if not import_task.done():
            import_task.cancel()
        await websocket.close()


@router.websocket("/ws/huggingface/models/import")
async def websocket_import_model_from_huggingface(websocket: WebSocket):
    await websocket.accept()

    try:
        data = await websocket.receive_json()
        request = HuggingFaceModelImportRequest(**data)
    except ValidationError as e:
        await websocket.send_json({"type": "error", "error": str(e)})
        await websocket.close()
        return
    except Exception:
        await websocket.send_json({"type": "error", "error": "Invalid request"})
        await websocket.close()
        return

    progress_queue: asyncio.Queue = asyncio.Queue()
    main_loop = asyncio.get_running_loop()

    def progress_callback(progress: dict) -> None:
        asyncio.run_coroutine_threadsafe(progress_queue.put(progress), main_loop)

    async def run_import() -> None:
        try:
            result = await main_loop.run_in_executor(
                _executor,
                lambda: _import_model_from_huggingface(request, progress_callback),
            )
            await progress_queue.put({"type": "complete", **result.model_dump()})
        except HTTPException as e:
            await progress_queue.put({"type": "error", "error": e.detail})
        except Exception as e:
            await progress_queue.put({"type": "error", "error": str(e)})

    import_task = asyncio.create_task(run_import())

    try:
        while True:
            try:
                progress = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                await websocket.send_json(progress)
                if progress.get("type") in ("complete", "error"):
                    break
            except asyncio.TimeoutError:
                if import_task.done():
                    break
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected during HF model import")
    except Exception as e:
        logger.error(f"WebSocket HF model import error: {e}")
    finally:
        if not import_task.done():
            import_task.cancel()
        await websocket.close()


@router.websocket("/ws/huggingface/datasets/{dataset_id:path}/export")
async def websocket_export_dataset_to_huggingface(websocket: WebSocket, dataset_id: str):
    await websocket.accept()

    try:
        data = await websocket.receive_json()
        request = HuggingFaceExportRequest(**data)
    except ValidationError as e:
        await websocket.send_json({"type": "error", "error": str(e)})
        await websocket.close()
        return
    except Exception:
        await websocket.send_json({"type": "error", "error": "Invalid request"})
        await websocket.close()
        return

    progress_queue: asyncio.Queue = asyncio.Queue()
    main_loop = asyncio.get_running_loop()

    def progress_callback(progress: dict) -> None:
        asyncio.run_coroutine_threadsafe(progress_queue.put(progress), main_loop)

    async def run_export() -> None:
        try:
            result = await main_loop.run_in_executor(
                _executor,
                lambda: _export_dataset_to_huggingface(dataset_id, request, progress_callback),
            )
            await progress_queue.put({"type": "complete", **result.model_dump()})
        except HTTPException as e:
            await progress_queue.put({"type": "error", "error": e.detail})
        except Exception as e:
            await progress_queue.put({"type": "error", "error": str(e)})

    export_task = asyncio.create_task(run_export())

    try:
        while True:
            try:
                progress = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                await websocket.send_json(progress)
                if progress.get("type") in ("complete", "error"):
                    break
            except asyncio.TimeoutError:
                if export_task.done():
                    break
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected during HF dataset export")
    except Exception as e:
        logger.error(f"WebSocket HF dataset export error: {e}")
    finally:
        if not export_task.done():
            export_task.cancel()
        await websocket.close()


@router.websocket("/ws/huggingface/models/{model_id}/export")
async def websocket_export_model_to_huggingface(websocket: WebSocket, model_id: str):
    await websocket.accept()

    try:
        data = await websocket.receive_json()
        request = HuggingFaceExportRequest(**data)
    except ValidationError as e:
        await websocket.send_json({"type": "error", "error": str(e)})
        await websocket.close()
        return
    except Exception:
        await websocket.send_json({"type": "error", "error": "Invalid request"})
        await websocket.close()
        return

    progress_queue: asyncio.Queue = asyncio.Queue()
    main_loop = asyncio.get_running_loop()

    def progress_callback(progress: dict) -> None:
        asyncio.run_coroutine_threadsafe(progress_queue.put(progress), main_loop)

    async def run_export() -> None:
        try:
            result = await main_loop.run_in_executor(
                _executor,
                lambda: _export_model_to_huggingface(model_id, request, progress_callback),
            )
            await progress_queue.put({"type": "complete", **result.model_dump()})
        except HTTPException as e:
            await progress_queue.put({"type": "error", "error": e.detail})
        except Exception as e:
            await progress_queue.put({"type": "error", "error": str(e)})

    export_task = asyncio.create_task(run_export())

    try:
        while True:
            try:
                progress = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                await websocket.send_json(progress)
                if progress.get("type") in ("complete", "error"):
                    break
            except asyncio.TimeoutError:
                if export_task.done():
                    break
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected during HF model export")
    except Exception as e:
        logger.error(f"WebSocket HF model export error: {e}")
    finally:
        if not export_task.done():
            export_task.cancel()
        await websocket.close()
