"""Storage API router for datasets and models management."""

import logging
import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from interfaces_backend.models.storage import (
    ArchiveListResponse,
    ArchiveResponse,
    DatasetListResponse,
    DatasetMetadata,
    DataSource,
    DataStatus,
    DownloadResponse,
    ModelListResponse,
    ModelMetadata,
    PublishRequest,
    PublishResponse,
    StorageUsageResponse,
    SyncRequest,
    SyncStatusResponse,
    UploadResponse,
)
from interfaces_backend.services.storage import (
    HuggingFaceService,
    ManifestManager,
    R2SyncService,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/storage", tags=["storage"])

# Global instances (initialized on first use)
_manifest_manager: Optional[ManifestManager] = None
_sync_service: Optional[R2SyncService] = None
_hf_service: Optional[HuggingFaceService] = None


def _get_manifest() -> ManifestManager:
    """Get or create manifest manager."""
    global _manifest_manager
    if _manifest_manager is None:
        _manifest_manager = ManifestManager()
        _manifest_manager.init_directories()
    return _manifest_manager


def _get_sync_service() -> R2SyncService:
    """Get or create R2 sync service."""
    global _sync_service
    if _sync_service is None:
        bucket = os.getenv("R2_BUCKET", "percus-data")
        version = os.getenv("R2_VERSION", "v2")
        _sync_service = R2SyncService(_get_manifest(), bucket, version=version)
    return _sync_service


def _get_hf_service() -> HuggingFaceService:
    """Get or create HuggingFace service."""
    global _hf_service
    if _hf_service is None:
        _hf_service = HuggingFaceService(_get_manifest())
    return _hf_service


# --- Dataset Endpoints ---


@router.get("/datasets", response_model=DatasetListResponse)
async def list_datasets(
    source: Optional[DataSource] = Query(None, description="Filter by source"),
    include_archived: bool = Query(False, description="Include archived datasets"),
):
    """List all datasets."""
    manifest = _get_manifest()

    if include_archived:
        active = manifest.list_datasets(source=source, status=DataStatus.ACTIVE)
        archived = manifest.list_datasets(source=source, status=DataStatus.ARCHIVED)
        datasets = active + archived
    else:
        datasets = manifest.list_datasets(source=source, status=DataStatus.ACTIVE)

    return DatasetListResponse(datasets=datasets, total=len(datasets))


@router.get("/datasets/{dataset_id}", response_model=DatasetMetadata)
async def get_dataset(dataset_id: str):
    """Get dataset details."""
    manifest = _get_manifest()
    dataset = manifest.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    return dataset


@router.post("/datasets/{dataset_id}/upload", response_model=UploadResponse)
async def upload_dataset(dataset_id: str):
    """Upload dataset to R2."""
    sync = _get_sync_service()
    success = sync.upload_dataset(dataset_id)

    if not success:
        raise HTTPException(status_code=500, detail="Upload failed")

    dataset = _get_manifest().get_dataset(dataset_id)
    return UploadResponse(
        id=dataset_id,
        success=True,
        message="Dataset uploaded successfully",
        size_bytes=dataset.sync.size_bytes if dataset else 0,
        hash=dataset.sync.hash if dataset else None,
    )


@router.post("/datasets/{dataset_id}/download", response_model=DownloadResponse)
async def download_dataset(dataset_id: str, request: Optional[SyncRequest] = None):
    """Download dataset from R2."""
    sync = _get_sync_service()

    episodes = None
    include_videos = True
    if request:
        episodes = request.episodes
        include_videos = request.include_videos

    success = sync.download_dataset(
        dataset_id,
        episodes=episodes,
        include_videos=include_videos,
    )

    if not success:
        raise HTTPException(status_code=500, detail="Download failed")

    dataset = _get_manifest().get_dataset(dataset_id)
    return DownloadResponse(
        id=dataset_id,
        success=True,
        message="Dataset downloaded successfully",
        size_bytes=dataset.sync.size_bytes if dataset else 0,
        hash=dataset.sync.hash if dataset else None,
    )


@router.post("/datasets/{dataset_id}/publish", response_model=PublishResponse)
async def publish_dataset(dataset_id: str, request: PublishRequest):
    """Publish dataset to HuggingFace Hub."""
    hf = _get_hf_service()
    repo_url = hf.publish_dataset(
        dataset_id,
        repo_id=request.repo_id,
        private=request.private,
        commit_message=request.commit_message,
    )

    if not repo_url:
        raise HTTPException(status_code=500, detail="Publish failed")

    return PublishResponse(
        id=dataset_id,
        success=True,
        message="Dataset published successfully",
        repo_url=repo_url,
    )


@router.delete("/datasets/{dataset_id}", response_model=ArchiveResponse)
async def archive_dataset(dataset_id: str):
    """Archive (soft delete) a dataset."""
    manifest = _get_manifest()
    success = manifest.archive_dataset(dataset_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    return ArchiveResponse(
        id=dataset_id,
        success=True,
        message="Dataset archived",
        status=DataStatus.ARCHIVED,
    )


@router.post("/datasets/{dataset_id}/restore", response_model=ArchiveResponse)
async def restore_dataset(dataset_id: str):
    """Restore dataset from archive."""
    manifest = _get_manifest()
    success = manifest.restore_dataset(dataset_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Dataset not found or not archived: {dataset_id}")

    return ArchiveResponse(
        id=dataset_id,
        success=True,
        message="Dataset restored",
        status=DataStatus.ACTIVE,
    )


@router.get("/datasets/{dataset_id}/sync", response_model=SyncStatusResponse)
async def check_dataset_sync(dataset_id: str):
    """Check sync status for a dataset."""
    sync = _get_sync_service()
    status = sync.check_dataset_sync(dataset_id)

    if not status:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    return SyncStatusResponse(
        id=status.id,
        source=status.source,
        local_hash=status.local_hash,
        remote_hash=status.remote_hash,
        is_synced=status.is_synced,
        local_size_bytes=status.local_size_bytes,
        remote_size_bytes=status.remote_size_bytes,
    )


# --- Model Endpoints ---


@router.get("/models", response_model=ModelListResponse)
async def list_models(
    source: Optional[DataSource] = Query(None, description="Filter by source"),
    include_archived: bool = Query(False, description="Include archived models"),
):
    """List all models."""
    manifest = _get_manifest()

    if include_archived:
        active = manifest.list_models(source=source, status=DataStatus.ACTIVE)
        archived = manifest.list_models(source=source, status=DataStatus.ARCHIVED)
        models = active + archived
    else:
        models = manifest.list_models(source=source, status=DataStatus.ACTIVE)

    return ModelListResponse(models=models, total=len(models))


@router.get("/models/{model_id}", response_model=ModelMetadata)
async def get_model(model_id: str):
    """Get model details."""
    manifest = _get_manifest()
    model = manifest.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    return model


@router.post("/models/{model_id}/upload", response_model=UploadResponse)
async def upload_model(model_id: str):
    """Upload model to R2."""
    sync = _get_sync_service()
    success = sync.upload_model(model_id)

    if not success:
        raise HTTPException(status_code=500, detail="Upload failed")

    model = _get_manifest().get_model(model_id)
    return UploadResponse(
        id=model_id,
        success=True,
        message="Model uploaded successfully",
        size_bytes=model.sync.size_bytes if model else 0,
        hash=model.sync.hash if model else None,
    )


@router.post("/models/{model_id}/download", response_model=DownloadResponse)
async def download_model(model_id: str):
    """Download model from R2."""
    sync = _get_sync_service()
    success = sync.download_model(model_id)

    if not success:
        raise HTTPException(status_code=500, detail="Download failed")

    model = _get_manifest().get_model(model_id)
    return DownloadResponse(
        id=model_id,
        success=True,
        message="Model downloaded successfully",
        size_bytes=model.sync.size_bytes if model else 0,
        hash=model.sync.hash if model else None,
    )


@router.post("/models/{model_id}/publish", response_model=PublishResponse)
async def publish_model(model_id: str, request: PublishRequest):
    """Publish model to HuggingFace Hub."""
    hf = _get_hf_service()
    repo_url = hf.publish_model(
        model_id,
        repo_id=request.repo_id,
        private=request.private,
        commit_message=request.commit_message,
    )

    if not repo_url:
        raise HTTPException(status_code=500, detail="Publish failed")

    return PublishResponse(
        id=model_id,
        success=True,
        message="Model published successfully",
        repo_url=repo_url,
    )


@router.delete("/models/{model_id}", response_model=ArchiveResponse)
async def archive_model(model_id: str):
    """Archive (soft delete) a model."""
    manifest = _get_manifest()
    success = manifest.archive_model(model_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")

    return ArchiveResponse(
        id=model_id,
        success=True,
        message="Model archived",
        status=DataStatus.ARCHIVED,
    )


@router.post("/models/{model_id}/restore", response_model=ArchiveResponse)
async def restore_model(model_id: str):
    """Restore model from archive."""
    manifest = _get_manifest()
    success = manifest.restore_model(model_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Model not found or not archived: {model_id}")

    return ArchiveResponse(
        id=model_id,
        success=True,
        message="Model restored",
        status=DataStatus.ACTIVE,
    )


@router.get("/models/{model_id}/sync", response_model=SyncStatusResponse)
async def check_model_sync(model_id: str):
    """Check sync status for a model."""
    sync = _get_sync_service()
    status = sync.check_model_sync(model_id)

    if not status:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")

    return SyncStatusResponse(
        id=status.id,
        source=status.source,
        local_hash=status.local_hash,
        remote_hash=status.remote_hash,
        is_synced=status.is_synced,
        local_size_bytes=status.local_size_bytes,
        remote_size_bytes=status.remote_size_bytes,
    )


# --- Import from HuggingFace ---


@router.post("/import/dataset", response_model=DatasetMetadata)
async def import_dataset_from_hf(
    repo_id: str = Query(..., description="HuggingFace repo ID (e.g., lerobot/pusht)"),
    force: bool = Query(False, description="Overwrite if exists"),
):
    """Import dataset from HuggingFace Hub."""
    hf = _get_hf_service()
    metadata = hf.import_dataset(repo_id, force=force)

    if not metadata:
        raise HTTPException(status_code=500, detail="Import failed")

    return metadata


@router.post("/import/model", response_model=ModelMetadata)
async def import_model_from_hf(
    repo_id: str = Query(..., description="HuggingFace repo ID"),
    force: bool = Query(False, description="Overwrite if exists"),
):
    """Import model from HuggingFace Hub."""
    hf = _get_hf_service()
    metadata = hf.import_model(repo_id, force=force)

    if not metadata:
        raise HTTPException(status_code=500, detail="Import failed")

    return metadata


# --- Storage Info ---


@router.get("/usage", response_model=StorageUsageResponse)
async def get_storage_usage():
    """Get storage usage statistics."""
    manifest = _get_manifest()
    stats = manifest.get_storage_stats()
    return StorageUsageResponse(**stats)


@router.get("/archive", response_model=ArchiveListResponse)
async def list_archived():
    """List archived datasets and models."""
    manifest = _get_manifest()

    datasets = manifest.list_datasets(status=DataStatus.ARCHIVED)
    models = manifest.list_models(status=DataStatus.ARCHIVED)

    return ArchiveListResponse(
        datasets=datasets,
        models=models,
        total=len(datasets) + len(models),
    )


# --- Sync Operations ---


@router.post("/sync/manifest/push")
async def push_manifest():
    """Push local manifest to R2."""
    sync = _get_sync_service()
    success = sync.sync_manifest_to_r2()

    if not success:
        raise HTTPException(status_code=500, detail="Manifest push failed")

    return {"success": True, "message": "Manifest pushed to R2"}


@router.post("/sync/manifest/pull")
async def pull_manifest(merge: bool = Query(True, description="Merge with local manifest")):
    """Pull manifest from R2."""
    sync = _get_sync_service()
    success = sync.sync_manifest_from_r2(merge=merge)

    if not success:
        raise HTTPException(status_code=500, detail="Manifest pull failed")

    return {"success": True, "message": "Manifest pulled from R2"}


# --- Search ---


@router.get("/search/datasets")
async def search_hub_datasets(
    query: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
):
    """Search datasets on HuggingFace Hub."""
    hf = _get_hf_service()
    results = hf.search_datasets(query, limit)
    return {"results": results, "total": len(results)}


@router.get("/search/models")
async def search_hub_models(
    query: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
):
    """Search models on HuggingFace Hub."""
    hf = _get_hf_service()
    results = hf.search_models(query, limit)
    return {"results": results, "total": len(results)}
