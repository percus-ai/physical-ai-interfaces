"""Storage API router for datasets/models (DB-backed)."""

import logging
import shutil
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from huggingface_hub import HfApi, snapshot_download, upload_folder

from interfaces_backend.models.storage import (
    ArchiveListResponse,
    ArchiveBulkRequest,
    ArchiveBulkResponse,
    ArchiveResponse,
    DatasetInfo,
    DatasetListResponse,
    HuggingFaceDatasetImportRequest,
    HuggingFaceExportRequest,
    HuggingFaceModelImportRequest,
    HuggingFaceTransferResponse,
    ModelInfo,
    ModelListResponse,
    StorageUsageResponse,
)
from percus_ai.db import get_supabase_client
from percus_ai.storage.hub import download_model, ensure_hf_token, get_local_model_info, upload_model
from percus_ai.storage.paths import get_datasets_dir, get_models_dir
from percus_ai.storage.r2_db_sync import R2DBSyncService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/storage", tags=["storage"])


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
    client = get_supabase_client()
    payload = {
        "id": dataset_id,
        "project_id": project_id,
        "name": name,
        "dataset_type": "huggingface",
        "source": "huggingface",
        "status": "active",
    }
    client.table("datasets").upsert(payload, on_conflict="id").execute()


def _upsert_model_from_hf(
    model_id: str,
    project_id: str,
    name: str,
    dataset_id: Optional[str],
    policy_type: Optional[str],
) -> None:
    client = get_supabase_client()
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
    client.table("models").upsert(payload, on_conflict="id").execute()


@router.post("/huggingface/datasets/import", response_model=HuggingFaceTransferResponse)
async def import_dataset_from_huggingface(request: HuggingFaceDatasetImportRequest):
    if not ensure_hf_token():
        raise HTTPException(status_code=400, detail="HF_TOKEN is required")
    dataset_id = request.dataset_id
    local_path = get_datasets_dir() / dataset_id
    if local_path.exists():
        if request.force:
            shutil.rmtree(local_path)
        else:
            raise HTTPException(status_code=409, detail=f"Dataset already exists: {dataset_id}")

    local_path.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=request.repo_id,
        repo_type="dataset",
        local_dir=str(local_path),
        local_dir_use_symlinks=False,
    )

    name = request.name or dataset_id.split("/")[-1]
    _upsert_dataset_from_hf(dataset_id, request.project_id, name)

    sync_service = R2DBSyncService()
    ok, error = sync_service.upload_dataset_with_progress(dataset_id, None)
    if not ok:
        raise HTTPException(status_code=500, detail=f"R2 upload failed: {error}")

    return HuggingFaceTransferResponse(
        success=True,
        message="Dataset imported from HuggingFace",
        item_id=dataset_id,
        repo_url=f"https://huggingface.co/datasets/{request.repo_id}",
    )


@router.post("/huggingface/models/import", response_model=HuggingFaceTransferResponse)
async def import_model_from_huggingface(request: HuggingFaceModelImportRequest):
    if not ensure_hf_token():
        raise HTTPException(status_code=400, detail="HF_TOKEN is required")
    model_id = request.model_id
    local_path = get_models_dir() / model_id
    if local_path.exists():
        if request.force:
            shutil.rmtree(local_path)
        else:
            raise HTTPException(status_code=409, detail=f"Model already exists: {model_id}")

    download_model(repo_id=request.repo_id, output_dir=local_path, force=request.force)
    local_info = get_local_model_info(local_path)
    policy_type = local_info.policy_type if local_info else None
    name = request.name or model_id

    _upsert_model_from_hf(model_id, request.project_id, name, request.dataset_id, policy_type)

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


@router.post("/huggingface/datasets/{dataset_id:path}/export", response_model=HuggingFaceTransferResponse)
async def export_dataset_to_huggingface(dataset_id: str, request: HuggingFaceExportRequest):
    if not ensure_hf_token():
        raise HTTPException(status_code=400, detail="HF_TOKEN is required")
    sync_service = R2DBSyncService()
    result = sync_service.ensure_dataset_local(dataset_id, auto_download=True)
    if not result.success:
        raise HTTPException(status_code=500, detail=f"Dataset download failed: {result.message}")

    local_path = get_datasets_dir() / dataset_id
    if not local_path.exists():
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

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

    return HuggingFaceTransferResponse(
        success=True,
        message="Dataset exported to HuggingFace",
        item_id=dataset_id,
        repo_url=f"https://huggingface.co/datasets/{request.repo_id}",
    )


@router.post("/huggingface/models/{model_id}/export", response_model=HuggingFaceTransferResponse)
async def export_model_to_huggingface(model_id: str, request: HuggingFaceExportRequest):
    if not ensure_hf_token():
        raise HTTPException(status_code=400, detail="HF_TOKEN is required")
    sync_service = R2DBSyncService()
    result = sync_service.ensure_model_local(model_id, auto_download=True)
    if not result.success:
        raise HTTPException(status_code=500, detail=f"Model download failed: {result.message}")

    local_path = get_models_dir() / model_id
    if not local_path.exists():
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")

    repo_url = upload_model(
        local_path=local_path,
        repo_id=request.repo_id,
        private=request.private,
        commit_message=request.commit_message,
    )

    return HuggingFaceTransferResponse(
        success=True,
        message="Model exported to HuggingFace",
        item_id=model_id,
        repo_url=repo_url,
    )
