"""Storage API router for datasets/models (DB-backed)."""

import asyncio
import logging
from pathlib import Path
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from huggingface_hub import HfApi, snapshot_download, upload_folder
from postgrest.exceptions import APIError
from pydantic import ValidationError

from interfaces_backend.models.storage import (
    ArchiveListResponse,
    ArchiveBulkRequest,
    ArchiveBulkResponse,
    ArchiveResponse,
    DatasetPlaybackCameraInfo,
    DatasetPlaybackResponse,
    DatasetReuploadResponse,
    DatasetMergeRequest,
    DatasetMergeResponse,
    DatasetInfo,
    DatasetListResponse,
    HuggingFaceDatasetImportRequest,
    HuggingFaceExportRequest,
    HuggingFaceModelImportRequest,
    HuggingFaceTransferResponse,
    ModelInfo,
    ModelListResponse,
    ModelSyncJobAcceptedResponse,
    ModelSyncJobCancelResponse,
    ModelSyncJobListResponse,
    ModelSyncJobStatus,
    StorageUsageResponse,
)
from interfaces_backend.services.dataset_lifecycle import get_dataset_lifecycle
from interfaces_backend.services.model_sync_jobs import get_model_sync_jobs_service
from interfaces_backend.services.session_manager import require_user_id
from interfaces_backend.services.vlabor_profiles import resolve_profile_spec
from percus_ai.db import get_supabase_async_client, upsert_with_owner
from percus_ai.storage.hash import compute_directory_hash, compute_directory_size
from percus_ai.storage.hub import download_model, ensure_hf_token, get_local_model_info, upload_model
from percus_ai.storage.naming import validate_dataset_name, generate_dataset_id
from percus_ai.storage.paths import get_datasets_dir, get_models_dir
from percus_ai.storage.r2_db_sync import ModelSyncCancelledError, R2DBSyncService
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


def _camera_label_from_key(video_key: str) -> str:
    prefix = "observation.images."
    if video_key.startswith(prefix):
        return video_key[len(prefix) :]
    return video_key.split(".")[-1]


def _build_playback_response(dataset_id: str, metadata: LeRobotDatasetMetadata) -> DatasetPlaybackResponse:
    cameras: list[DatasetPlaybackCameraInfo] = []
    for video_key in metadata.video_keys:
        feature = metadata.features.get(video_key) if isinstance(metadata.features, dict) else None
        info = feature.get("info") if isinstance(feature, dict) else {}
        cameras.append(
            DatasetPlaybackCameraInfo(
                key=video_key,
                label=_camera_label_from_key(video_key),
                width=info.get("video.width"),
                height=info.get("video.height"),
                fps=info.get("video.fps"),
                codec=info.get("video.codec"),
                pix_fmt=info.get("video.pix_fmt"),
            )
        )

    return DatasetPlaybackResponse(
        dataset_id=dataset_id,
        is_local=True,
        total_episodes=metadata.total_episodes,
        fps=metadata.fps,
        use_videos=bool(metadata.video_path) and len(metadata.video_keys) > 0,
        cameras=cameras,
    )


async def _detach_models_from_dataset(client, dataset_id: str) -> None:
    await client.table("models").update({"dataset_id": None}).eq("dataset_id", dataset_id).execute()


async def _detach_training_jobs_from_dataset(client, dataset_id: str) -> None:
    await client.table("training_jobs").update({"dataset_id": None}).eq("dataset_id", dataset_id).execute()
    try:
        await (
            client.table("training_jobs")
            .update({"new_dataset_id": None})
            .eq("new_dataset_id", dataset_id)
            .execute()
        )
    except APIError as exc:
        if _is_missing_column_error(exc, table_name="training_jobs", column_name="new_dataset_id"):
            logger.info("Skip training_jobs.new_dataset_id detach: column not found")
            return
        raise


async def _detach_dataset_references(client, dataset_id: str) -> None:
    await _detach_models_from_dataset(client, dataset_id)
    await _detach_training_jobs_from_dataset(client, dataset_id)


def _is_missing_column_error(exc: APIError, *, table_name: str, column_name: str) -> bool:
    if str(getattr(exc, "code", "")).strip() != "PGRST204":
        return False
    message = str(getattr(exc, "message", "") or "").lower()
    return table_name.lower() in message and column_name.lower() in message


def _extract_profile_name(snapshot: object) -> Optional[str]:
    if not isinstance(snapshot, dict):
        return None
    name = snapshot.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    profile = snapshot.get("profile")
    if isinstance(profile, dict):
        nested_name = profile.get("name")
        if isinstance(nested_name, str) and nested_name.strip():
            return nested_name.strip()
    return None


def _dataset_row_to_info(row: dict) -> DatasetInfo:
    profile_snapshot = row.get("profile_snapshot")
    return DatasetInfo(
        id=row.get("id"),
        name=row.get("name") or row.get("id"),
        profile_name=_extract_profile_name(profile_snapshot),
        profile_snapshot=profile_snapshot if isinstance(profile_snapshot, dict) else None,
        source=row.get("source") or "r2",
        status=row.get("status") or "active",
        dataset_type=row.get("dataset_type") or "recorded",
        episode_count=row.get("episode_count") or 0,
        size_bytes=row.get("size_bytes") or 0,
        is_local=_dataset_is_local(row.get("id")),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _model_row_to_info(row: dict) -> ModelInfo:
    model_id = row.get("id")
    profile_snapshot = row.get("profile_snapshot")
    return ModelInfo(
        id=model_id,
        name=row.get("name") or model_id,
        dataset_id=row.get("dataset_id"),
        profile_name=_extract_profile_name(profile_snapshot),
        profile_snapshot=profile_snapshot if isinstance(profile_snapshot, dict) else None,
        policy_type=row.get("policy_type"),
        training_steps=row.get("training_steps"),
        batch_size=row.get("batch_size"),
        size_bytes=row.get("size_bytes") or 0,
        is_local=_model_is_local(str(model_id)) if model_id else False,
        source=row.get("source") or "r2",
        status=row.get("status") or "active",
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


@router.get("/datasets", response_model=DatasetListResponse)
async def list_datasets(
    include_archived: bool = Query(False, description="Include archived datasets"),
    profile_name: Optional[str] = Query(None, description="Filter by profile name"),
):
    """List datasets from DB."""
    client = await get_supabase_async_client()
    query = client.table("datasets").select("*")
    if not include_archived:
        query = query.eq("status", "active")
    rows = (await query.execute()).data or []
    if profile_name:
        rows = [row for row in rows if _extract_profile_name(row.get("profile_snapshot")) == profile_name]

    datasets = [_dataset_row_to_info(row) for row in rows]
    return DatasetListResponse(datasets=datasets, total=len(datasets))


async def _merge_datasets(
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

    merged_dataset_id = generate_dataset_id()
    client = await get_supabase_async_client()

    report({"type": "start", "step": "validate", "message": "Validating datasets"})
    source_rows = []
    for dataset_id in source_dataset_ids:
        rows = (
            await client.table("datasets").select("*").eq("id", dataset_id).execute()
        ).data or []
        if not rows:
            raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
        row = rows[0]
        if row.get("status") != "active":
            raise HTTPException(status_code=400, detail=f"Dataset is not active: {dataset_id}")
        source_rows.append(row)
    report({"type": "step_complete", "step": "validate", "message": "Validation complete"})

    profile_names = {
        profile_name
        for row in source_rows
        for profile_name in [_extract_profile_name(row.get("profile_snapshot"))]
        if profile_name
    }
    if len(profile_names) > 1:
        raise HTTPException(status_code=400, detail="Profile mismatch across source datasets")
    profile_snapshot = next(
        (row.get("profile_snapshot") for row in source_rows if isinstance(row.get("profile_snapshot"), dict)),
        None,
    )

    report({"type": "start", "step": "download", "message": "Ensuring local datasets"})
    sync_service = R2DBSyncService()
    for dataset_id in source_dataset_ids:
        report({"type": "progress", "step": "download", "dataset_id": dataset_id})
        result = await sync_service.ensure_dataset_local(dataset_id, auto_download=True)
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
    ok, error = await sync_service.upload_dataset_with_progress(merged_dataset_id, upload_progress)
    if not ok:
        shutil.rmtree(merged_root)
        raise HTTPException(status_code=500, detail=f"R2 upload failed: {error}")
    report({"type": "step_complete", "step": "upload", "message": "Upload complete"})

    payload = {
        "id": merged_dataset_id,
        "name": request.dataset_name,
        "profile_snapshot": profile_snapshot,
        "episode_count": episode_count,
        "dataset_type": "merged",
        "source": "r2",
        "status": "active",
        "size_bytes": size_bytes,
        "content_hash": content_hash,
    }
    await upsert_with_owner("datasets", "id", payload)

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
    return await _merge_datasets(request)


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

    def _merge_datasets_sync() -> DatasetMergeResponse:
        return asyncio.run(_merge_datasets(request, progress_callback))

    async def run_merge() -> None:
        try:
            result = await main_loop.run_in_executor(_executor, _merge_datasets_sync)
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
    client = await get_supabase_async_client()
    rows = (await client.table("datasets").select("*").eq("id", dataset_id).execute()).data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    return _dataset_row_to_info(rows[0])


@router.get("/datasets/{dataset_id:path}/playback", response_model=DatasetPlaybackResponse)
async def get_dataset_playback(dataset_id: str):
    """Get local playback metadata for a dataset."""
    client = await get_supabase_async_client()
    rows = (await client.table("datasets").select("id").eq("id", dataset_id).execute()).data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    dataset_path = get_datasets_dir() / dataset_id
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail=f"Local dataset not found: {dataset_id}")

    try:
        metadata = LeRobotDatasetMetadata(dataset_id, root=dataset_path)
        return _build_playback_response(dataset_id, metadata)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load dataset playback metadata: {exc}") from exc


@router.get("/datasets/{dataset_id:path}/playback/{video_key:path}/{episode_index}")
async def get_dataset_playback_video(dataset_id: str, video_key: str, episode_index: int):
    """Stream a dataset episode video for playback."""
    if episode_index < 0:
        raise HTTPException(status_code=400, detail="episode_index must be >= 0")

    client = await get_supabase_async_client()
    rows = (await client.table("datasets").select("id").eq("id", dataset_id).execute()).data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    dataset_path = get_datasets_dir() / dataset_id
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail=f"Local dataset not found: {dataset_id}")

    try:
        metadata = LeRobotDatasetMetadata(dataset_id, root=dataset_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load dataset metadata: {exc}") from exc

    if video_key not in metadata.video_keys:
        raise HTTPException(status_code=404, detail=f"Video stream not found: {video_key}")
    if episode_index >= metadata.total_episodes:
        raise HTTPException(
            status_code=404,
            detail=f"Episode index out of range: {episode_index} (total={metadata.total_episodes})",
        )

    relative_path = metadata.get_video_file_path(episode_index, video_key)
    video_path = Path(dataset_path) / relative_path
    if not video_path.exists():
        raise HTTPException(status_code=404, detail=f"Video file not found: {relative_path}")

    return FileResponse(
        path=video_path,
        media_type="video/mp4",
        filename=video_path.name,
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/datasets/{dataset_id:path}", response_model=ArchiveResponse)
async def archive_dataset(dataset_id: str):
    """Archive (soft delete) a dataset."""
    client = await get_supabase_async_client()
    existing = (
        await client.table("datasets").select("id").eq("id", dataset_id).execute()
    ).data or []
    if not existing:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    await client.table("datasets").update({"status": "archived"}).eq("id", dataset_id).execute()
    return ArchiveResponse(id=dataset_id, success=True, message="Dataset archived", status="archived")


@router.post("/datasets/{dataset_id:path}/restore", response_model=ArchiveResponse)
async def restore_dataset(dataset_id: str):
    """Restore dataset from archive."""
    client = await get_supabase_async_client()
    existing = (
        await client.table("datasets").select("id").eq("id", dataset_id).execute()
    ).data or []
    if not existing:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    await client.table("datasets").update({"status": "active"}).eq("id", dataset_id).execute()
    return ArchiveResponse(id=dataset_id, success=True, message="Dataset restored", status="active")


@router.post("/datasets/{dataset_id:path}/reupload", response_model=DatasetReuploadResponse)
async def reupload_dataset(dataset_id: str):
    dataset_id = dataset_id.strip()
    if not dataset_id:
        raise HTTPException(status_code=400, detail="Dataset ID is required")

    local_path = get_datasets_dir() / dataset_id
    if not local_path.exists():
        raise HTTPException(status_code=404, detail=f"Local dataset not found: {dataset_id}")
    if not local_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Invalid dataset path: {dataset_id}")

    lifecycle = get_dataset_lifecycle()
    ok, error = await lifecycle.reupload(dataset_id)
    if not ok:
        raise HTTPException(status_code=500, detail=f"Dataset re-upload failed: {error}")

    return DatasetReuploadResponse(
        id=dataset_id,
        success=True,
        message="Dataset re-upload completed",
    )


@router.get("/models", response_model=ModelListResponse)
async def list_models(
    include_archived: bool = Query(False, description="Include archived models"),
    profile_name: Optional[str] = Query(None, description="Filter by profile name"),
):
    """List models from DB."""
    client = await get_supabase_async_client()
    query = client.table("models").select("*")
    if not include_archived:
        query = query.eq("status", "active")
    rows = (await query.execute()).data or []
    if profile_name:
        rows = [row for row in rows if _extract_profile_name(row.get("profile_snapshot")) == profile_name]
    models = [_model_row_to_info(row) for row in rows]
    return ModelListResponse(models=models, total=len(models))


@router.get("/models/{model_id}", response_model=ModelInfo)
async def get_model(model_id: str):
    """Get model details from DB."""
    client = await get_supabase_async_client()
    rows = (await client.table("models").select("*").eq("id", model_id).execute()).data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    return _model_row_to_info(rows[0])


async def _run_model_sync_job(*, job_id: str, model_id: str) -> None:
    jobs = get_model_sync_jobs_service()
    sync_service = R2DBSyncService()
    progress_callback = jobs.build_progress_callback(job_id=job_id)
    cancel_event = jobs.get_cancel_event(job_id=job_id)
    try:
        result = await sync_service.ensure_model_local(
            model_id,
            auto_download=True,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )
    except ModelSyncCancelledError:
        jobs.cancelled(job_id=job_id)
        return
    except asyncio.CancelledError:
        jobs.cancelled(job_id=job_id)
        return
    except Exception as exc:
        logger.exception("Model sync job failed unexpectedly: %s", job_id)
        jobs.fail(
            job_id=job_id,
            message="モデル同期に失敗しました。",
            error=str(exc),
        )
    else:
        if result.success:
            jobs.complete(
                job_id=job_id,
                message="ローカルキャッシュを利用しました。" if result.skipped else "モデル同期が完了しました。",
            )
            return
        if result.cancelled:
            jobs.cancelled(job_id=job_id)
            return
        jobs.fail(
            job_id=job_id,
            message="モデル同期に失敗しました。",
            error=result.message,
        )
    finally:
        jobs.release_runtime_handles(job_id=job_id)


@router.post("/models/{model_id}/sync", response_model=ModelSyncJobAcceptedResponse, status_code=202)
async def sync_model(model_id: str):
    """Start a background model sync job."""
    model_id = model_id.strip()
    if not model_id:
        raise HTTPException(status_code=400, detail="Model ID is required")
    user_id = require_user_id()

    client = await get_supabase_async_client()
    rows = (
        await client.table("models").select("id,status").eq("id", model_id).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    if rows[0].get("status") != "active":
        raise HTTPException(status_code=400, detail="Model is not active")

    jobs = get_model_sync_jobs_service()
    accepted = jobs.create(user_id=user_id, model_id=model_id)
    task = asyncio.create_task(_run_model_sync_job(job_id=accepted.job_id, model_id=model_id))
    jobs.attach_task(user_id=user_id, job_id=accepted.job_id, task=task)
    return accepted


@router.get("/model-sync/jobs", response_model=ModelSyncJobListResponse)
async def list_model_sync_jobs(include_terminal: bool = Query(False, description="Include completed jobs")):
    user_id = require_user_id()
    jobs = get_model_sync_jobs_service()
    return jobs.list(user_id=user_id, include_terminal=include_terminal)


@router.get("/model-sync/jobs/{job_id}", response_model=ModelSyncJobStatus)
async def get_model_sync_job(job_id: str):
    user_id = require_user_id()
    jobs = get_model_sync_jobs_service()
    return jobs.get(user_id=user_id, job_id=job_id)


@router.post("/model-sync/jobs/{job_id}/cancel", response_model=ModelSyncJobCancelResponse)
async def cancel_model_sync_job(job_id: str):
    user_id = require_user_id()
    jobs = get_model_sync_jobs_service()
    return jobs.cancel(
        user_id=user_id,
        job_id=job_id,
    )


@router.delete("/models/{model_id}", response_model=ArchiveResponse)
async def archive_model(model_id: str):
    """Archive (soft delete) a model."""
    client = await get_supabase_async_client()
    existing = (
        await client.table("models").select("id").eq("id", model_id).execute()
    ).data or []
    if not existing:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    await client.table("models").update({"status": "archived"}).eq("id", model_id).execute()
    return ArchiveResponse(id=model_id, success=True, message="Model archived", status="archived")


@router.post("/models/{model_id}/restore", response_model=ArchiveResponse)
async def restore_model(model_id: str):
    """Restore model from archive."""
    client = await get_supabase_async_client()
    existing = (
        await client.table("models").select("id").eq("id", model_id).execute()
    ).data or []
    if not existing:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    await client.table("models").update({"status": "active"}).eq("id", model_id).execute()
    return ArchiveResponse(id=model_id, success=True, message="Model restored", status="active")


@router.get("/usage", response_model=StorageUsageResponse)
async def get_storage_usage():
    """Get storage usage statistics from DB."""
    client = await get_supabase_async_client()
    datasets = (await client.table("datasets").select("size_bytes,status").execute()).data or []
    models = (await client.table("models").select("size_bytes,status").execute()).data or []

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
    client = await get_supabase_async_client()
    datasets = (
        await client.table("datasets").select("*").eq("status", "archived").execute()
    ).data or []
    models = (
        await client.table("models").select("*").eq("status", "archived").execute()
    ).data or []
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
    client = await get_supabase_async_client()
    existing = (
        await client.table("datasets").select("id,status").eq("id", dataset_id).execute()
    ).data or []
    if not existing:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    if existing[0].get("status") != "archived":
        raise HTTPException(status_code=400, detail="Dataset is not archived")

    await _detach_dataset_references(client, dataset_id)
    sync_service = R2DBSyncService()
    sync_service.delete_dataset_remote(dataset_id)
    _delete_local_dataset(dataset_id)
    await client.table("datasets").delete().eq("id", dataset_id).execute()
    return ArchiveResponse(id=dataset_id, success=True, message="Dataset deleted", status="deleted")


@router.delete("/archive/models/{model_id}", response_model=ArchiveResponse)
async def delete_archived_model(model_id: str):
    """Permanently delete an archived model."""
    client = await get_supabase_async_client()
    existing = (
        await client.table("models").select("id,status").eq("id", model_id).execute()
    ).data or []
    if not existing:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    if existing[0].get("status") != "archived":
        raise HTTPException(status_code=400, detail="Model is not archived")

    sync_service = R2DBSyncService()
    sync_service.delete_model_remote(model_id)
    _delete_local_model(model_id)
    await client.table("training_jobs").update({"model_id": None}).eq("model_id", model_id).execute()
    await client.table("models").delete().eq("id", model_id).execute()
    return ArchiveResponse(id=model_id, success=True, message="Model deleted", status="deleted")


@router.post("/archive/restore", response_model=ArchiveBulkResponse)
async def restore_archived_items(request: ArchiveBulkRequest):
    """Bulk restore archived datasets/models."""
    client = await get_supabase_async_client()
    restored: list[str] = []
    errors: list[str] = []

    for dataset_id in request.dataset_ids:
        existing = (
            await client.table("datasets").select("id,status").eq("id", dataset_id).execute()
        ).data or []
        if not existing:
            errors.append(f"Dataset not found: {dataset_id}")
            continue
        await client.table("datasets").update({"status": "active"}).eq("id", dataset_id).execute()
        restored.append(dataset_id)

    for model_id in request.model_ids:
        existing = (
            await client.table("models").select("id,status").eq("id", model_id).execute()
        ).data or []
        if not existing:
            errors.append(f"Model not found: {model_id}")
            continue
        await client.table("models").update({"status": "active"}).eq("id", model_id).execute()
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
    client = await get_supabase_async_client()
    sync_service = R2DBSyncService()
    deleted: list[str] = []
    errors: list[str] = []

    for dataset_id in request.dataset_ids:
        existing = (
            await client.table("datasets").select("id,status").eq("id", dataset_id).execute()
        ).data or []
        if not existing:
            errors.append(f"Dataset not found: {dataset_id}")
            continue
        if existing[0].get("status") != "archived":
            errors.append(f"Dataset is not archived: {dataset_id}")
            continue
        await _detach_dataset_references(client, dataset_id)
        sync_service.delete_dataset_remote(dataset_id)
        _delete_local_dataset(dataset_id)
        await client.table("datasets").delete().eq("id", dataset_id).execute()
        deleted.append(dataset_id)

    for model_id in request.model_ids:
        existing = (
            await client.table("models").select("id,status").eq("id", model_id).execute()
        ).data or []
        if not existing:
            errors.append(f"Model not found: {model_id}")
            continue
        if existing[0].get("status") != "archived":
            errors.append(f"Model is not archived: {model_id}")
            continue
        sync_service.delete_model_remote(model_id)
        _delete_local_model(model_id)
        await client.table("training_jobs").update({"model_id": None}).eq("model_id", model_id).execute()
        await client.table("models").delete().eq("id", model_id).execute()
        deleted.append(model_id)

    return ArchiveBulkResponse(
        success=len(errors) == 0,
        restored=[],
        deleted=deleted,
        errors=errors,
    )


async def _upsert_dataset_from_hf(
    dataset_id: str,
    name: str,
    profile_snapshot: Optional[dict],
) -> None:
    payload = {
        "id": dataset_id,
        "name": name,
        "profile_snapshot": profile_snapshot,
        "dataset_type": "huggingface",
        "source": "huggingface",
        "status": "active",
    }
    await upsert_with_owner("datasets", "id", payload)


async def _upsert_model_from_hf(
    model_id: str,
    name: str,
    dataset_id: Optional[str],
    profile_snapshot: Optional[dict],
    policy_type: Optional[str],
) -> None:
    payload = {
        "id": model_id,
        "name": name,
        "dataset_id": dataset_id,
        "profile_snapshot": profile_snapshot,
        "policy_type": policy_type,
        "model_type": "huggingface",
        "source": "huggingface",
        "status": "active",
    }
    await upsert_with_owner("models", "id", payload)


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


async def _import_dataset_from_huggingface(
    request: HuggingFaceDatasetImportRequest,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> HuggingFaceTransferResponse:
    if not ensure_hf_token():
        raise HTTPException(status_code=400, detail="HF_TOKEN is required")
    dataset_id = request.dataset_id or generate_dataset_id()
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

    name = request.dataset_name or request.name or request.repo_id.split("/")[-1]
    profile_name = request.profile_name.strip() if request.profile_name else None
    profile_snapshot = resolve_profile_spec(profile_name).snapshot if profile_name else None
    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "db_upsert",
            "message": "Registering dataset",
        })
    await _upsert_dataset_from_hf(dataset_id, name, profile_snapshot)
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "db_upsert",
            "message": "Dataset registered",
        })

    sync_service = R2DBSyncService()
    ok, error = await sync_service.upload_dataset_with_progress(
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


async def _import_model_from_huggingface(
    request: HuggingFaceModelImportRequest,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> HuggingFaceTransferResponse:
    if not ensure_hf_token():
        raise HTTPException(status_code=400, detail="HF_TOKEN is required")
    model_id = request.model_id or str(uuid.uuid4())
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
    name = request.model_name or model_id
    profile_name = request.profile_name.strip() if request.profile_name else None
    profile_snapshot = resolve_profile_spec(profile_name).snapshot if profile_name else None

    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "db_upsert",
            "message": "Registering model",
        })
    await _upsert_model_from_hf(
        model_id,
        name,
        request.dataset_id,
        profile_snapshot,
        policy_type,
    )
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "db_upsert",
            "message": "Model registered",
        })

    sync_service = R2DBSyncService()
    result = await sync_service.upload_model(model_id)
    if not result.success:
        raise HTTPException(status_code=500, detail=f"R2 upload failed: {result.message}")

    return HuggingFaceTransferResponse(
        success=True,
        message="Model imported from HuggingFace",
        item_id=model_id,
        repo_url=f"https://huggingface.co/{request.repo_id}",
    )


async def _export_dataset_to_huggingface(
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
    result = await sync_service.ensure_dataset_local(dataset_id, auto_download=True)
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


async def _export_model_to_huggingface(
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
    result = await sync_service.ensure_model_local(model_id, auto_download=True)
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
    return await _import_dataset_from_huggingface(request)


@router.post("/huggingface/models/import", response_model=HuggingFaceTransferResponse)
async def import_model_from_huggingface(request: HuggingFaceModelImportRequest):
    return await _import_model_from_huggingface(request)


@router.post("/huggingface/datasets/{dataset_id:path}/export", response_model=HuggingFaceTransferResponse)
async def export_dataset_to_huggingface(dataset_id: str, request: HuggingFaceExportRequest):
    return await _export_dataset_to_huggingface(dataset_id, request)


@router.post("/huggingface/models/{model_id}/export", response_model=HuggingFaceTransferResponse)
async def export_model_to_huggingface(model_id: str, request: HuggingFaceExportRequest):
    return await _export_model_to_huggingface(model_id, request)


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

    def _import_dataset_sync() -> HuggingFaceTransferResponse:
        return asyncio.run(_import_dataset_from_huggingface(request, progress_callback))

    async def run_import() -> None:
        try:
            result = await main_loop.run_in_executor(_executor, _import_dataset_sync)
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

    def _import_model_sync() -> HuggingFaceTransferResponse:
        return asyncio.run(_import_model_from_huggingface(request, progress_callback))

    async def run_import() -> None:
        try:
            result = await main_loop.run_in_executor(_executor, _import_model_sync)
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
                lambda: asyncio.run(_export_dataset_to_huggingface(dataset_id, request, progress_callback)),
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
                lambda: asyncio.run(_export_model_to_huggingface(model_id, request, progress_callback)),
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
