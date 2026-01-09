"""Storage API router for datasets and models management."""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from fastapi import APIRouter, Body, HTTPException, Query, WebSocket, WebSocketDisconnect

from percus_ai.storage import (
    DatasetMetadata,
    DataSource,
    DataStatus,
    HuggingFaceService,
    ManifestManager,
    ModelMetadata,
    R2SyncService,
)
from interfaces_backend.models.storage import (
    ArchiveListResponse,
    ArchiveResponse,
    DatasetInfo,
    DatasetListResponse,
    DownloadResponse,
    ModelListResponse,
    PublishRequest,
    PublishResponse,
    StorageUsageResponse,
    SyncRequest,
    SyncStatusResponse,
    UploadResponse,
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
    include_remote: bool = Query(True, description="Include R2 remote datasets"),
):
    """List all datasets.

    Returns both locally downloaded datasets and R2 remote datasets.
    Use is_local to check if a dataset needs to be downloaded before use.
    """
    manifest = _get_manifest()
    manifest.reload()  # Reload to pick up any external changes

    datasets_info = []
    seen_ids = set()

    # First, add local datasets (from manifest)
    if include_archived:
        active = manifest.list_datasets(source=source, status=DataStatus.ACTIVE)
        archived = manifest.list_datasets(source=source, status=DataStatus.ARCHIVED)
        local_datasets = active + archived
    else:
        local_datasets = manifest.list_datasets(source=source, status=DataStatus.ACTIVE)

    for ds in local_datasets:
        # Check if actually downloaded locally
        entry = manifest.manifest.datasets.get(ds.id)
        is_local = False
        if entry:
            local_path = manifest.base_path / entry.path
            is_local = local_path.exists()

        seen_ids.add(ds.id)
        datasets_info.append(DatasetInfo(
            id=ds.id,
            short_id=ds.short_id,
            name=ds.name,
            source=ds.source,
            status=ds.status,
            dataset_type=ds.dataset_type.value if ds.dataset_type else "recorded",
            episode_count=ds.recording.episode_count if ds.recording else 0,
            size_bytes=ds.sync.size_bytes if ds.sync else 0,
            is_local=is_local,
            created_at=ds.created_at,
            updated_at=ds.updated_at,
        ))

    # Then, add R2 remote datasets (not yet in manifest)
    if include_remote and (source is None or source == DataSource.R2):
        try:
            sync = _get_sync_service()
            remote_datasets = sync.list_remote_datasets()

            for rd in remote_datasets:
                dataset_id = rd.get("id", "")
                if not dataset_id or dataset_id in seen_ids:
                    continue

                datasets_info.append(DatasetInfo(
                    id=dataset_id,
                    name=rd.get("name", dataset_id),
                    source=DataSource.R2,
                    status=DataStatus.ACTIVE,
                    dataset_type=rd.get("dataset_type", "recorded"),
                    episode_count=rd.get("episode_count", 0),
                    size_bytes=rd.get("size_bytes", 0),
                    is_local=False,
                    created_at=None,
                    updated_at=None,
                ))
        except Exception as e:
            logger.debug(f"Failed to list remote datasets: {e}")

    return DatasetListResponse(datasets=datasets_info, total=len(datasets_info))


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
    manifest.reload()  # Reload to pick up any external changes

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
    manifest.reload()  # Reload to pick up any external changes
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


# --- Projects ---


@router.get("/projects")
async def list_projects():
    """List all projects."""
    manifest = _get_manifest()
    manifest.reload()
    projects = manifest.list_projects()
    return {"projects": [p.model_dump() for p in projects], "total": len(projects)}


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    """Get project details."""
    manifest = _get_manifest()
    project = manifest.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return project.model_dump()


@router.post("/projects/{project_id}/upload")
async def upload_project(project_id: str):
    """Upload project config to R2."""
    sync = _get_sync_service()
    success, error = sync.upload_project(project_id)

    if not success:
        raise HTTPException(status_code=500, detail=error or "Upload failed")

    return {"success": True, "project_id": project_id, "message": "Project uploaded"}


@router.post("/projects/{project_id}/download")
async def download_project(project_id: str):
    """Download project config from R2."""
    sync = _get_sync_service()
    success, error = sync.download_project(project_id)

    if not success:
        raise HTTPException(status_code=500, detail=error or "Download failed")

    return {"success": True, "project_id": project_id, "message": "Project downloaded"}


@router.get("/projects/remote/list")
async def list_remote_projects():
    """List projects available on R2."""
    sync = _get_sync_service()
    projects = sync.list_remote_projects()
    return {"projects": projects, "total": len(projects)}


@router.post("/projects/sync")
async def sync_projects():
    """Sync all projects from R2 (download missing ones)."""
    sync = _get_sync_service()
    downloaded, errors = sync.sync_projects_from_r2()
    return {"downloaded": downloaded, "errors": errors}


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


@router.post("/sync/manifest/regenerate")
async def regenerate_manifest():
    """Regenerate manifest by scanning R2 and local storage."""
    sync = _get_sync_service()
    stats = sync.regenerate_manifest()

    return {
        "success": True,
        "message": "Manifest regenerated",
        "remote_models": stats.get("remote_models", 0),
        "remote_datasets": stats.get("remote_datasets", 0),
        "local_models": stats.get("local_models", 0),
        "local_datasets": stats.get("local_datasets", 0),
    }


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


# --- Migration ---


@router.get("/migration/legacy/models")
async def list_legacy_models():
    """List models in legacy (root-level) storage."""
    sync = _get_sync_service()
    items = sync.list_legacy_items("models")
    return {"items": items, "total": len(items)}


@router.get("/migration/legacy/datasets")
async def list_legacy_datasets():
    """List datasets in legacy (root-level) storage."""
    sync = _get_sync_service()
    items = sync.list_legacy_items("datasets")
    return {"items": items, "total": len(items)}


@router.post("/migration/models")
async def migrate_models(
    item_ids: List[str] = Body(..., description="List of model IDs to migrate"),
    delete_legacy: bool = Body(False, description="Delete legacy items after migration"),
):
    """Migrate models from legacy to versioned storage."""
    sync = _get_sync_service()
    results = sync.migrate_items(item_ids, "models", delete_legacy=delete_legacy)

    success_count = sum(1 for v in results.values() if v.get("success"))
    failed_count = len(results) - success_count

    return {
        "results": results,
        "success_count": success_count,
        "failed_count": failed_count,
        "message": f"Migrated {success_count}/{len(results)} models",
    }


@router.post("/migration/datasets")
async def migrate_datasets(
    item_ids: List[str] = Body(..., description="List of dataset IDs to migrate"),
    delete_legacy: bool = Body(False, description="Delete legacy items after migration"),
):
    """Migrate datasets from legacy to versioned storage."""
    sync = _get_sync_service()
    results = sync.migrate_items(item_ids, "datasets", delete_legacy=delete_legacy)

    success_count = sum(1 for v in results.values() if v.get("success"))
    failed_count = len(results) - success_count

    return {
        "results": results,
        "success_count": success_count,
        "failed_count": failed_count,
        "message": f"Migrated {success_count}/{len(results)} datasets",
    }


# --- WebSocket Migration with Progress ---

# Thread pool for running sync operations
_executor = ThreadPoolExecutor(max_workers=2)


@router.websocket("/ws/migration")
async def websocket_migration(websocket: WebSocket):
    """WebSocket endpoint for migration with real-time progress.

    Client sends JSON messages:
    - {"action": "migrate", "entry_type": "models"|"datasets", "item_ids": [...], "delete_legacy": bool}

    Server sends progress updates:
    - {"type": "start", "item_id": "...", "total_files": N}
    - {"type": "copying", "item_id": "...", "current_file": "...", "file_size": N, "copied_files": M, "total_files": N}
    - {"type": "copied", "item_id": "...", "current_file": "...", "copied_files": M, "total_files": N}
    - {"type": "complete", "item_id": "...", "total_files": N}
    - {"type": "error", "item_id": "...", "error": "..."}
    - {"type": "done", "success_count": N, "failed_count": M, "results": {...}}
    """
    await websocket.accept()

    try:
        while True:
            # Wait for migration request
            data = await websocket.receive_json()

            action = data.get("action")
            if action != "migrate":
                await websocket.send_json({"type": "error", "error": "Unknown action"})
                continue

            entry_type = data.get("entry_type", "models")
            item_ids = data.get("item_ids", [])
            delete_legacy = data.get("delete_legacy", False)

            if not item_ids:
                await websocket.send_json({"type": "error", "error": "No items specified"})
                continue

            # Get sync service
            sync = _get_sync_service()

            # Queue for progress updates from thread
            progress_queue: asyncio.Queue = asyncio.Queue()

            # Capture event loop for use in thread callback
            main_loop = asyncio.get_running_loop()

            def progress_callback(progress: dict):
                """Callback to put progress in queue (called from thread)."""
                asyncio.run_coroutine_threadsafe(
                    progress_queue.put(progress),
                    main_loop
                )

            async def run_migration():
                """Run migration in thread pool."""
                results = {}
                success_count = 0
                failed_count = 0

                loop = asyncio.get_event_loop()

                for item_id in item_ids:
                    # Run in thread pool to avoid blocking
                    success, error = await loop.run_in_executor(
                        _executor,
                        lambda iid=item_id: sync.migrate_item_with_progress(
                            iid, entry_type, progress_callback
                        )
                    )
                    results[item_id] = {"success": success, "error": error}
                    if success:
                        success_count += 1
                        if delete_legacy:
                            try:
                                await loop.run_in_executor(
                                    _executor,
                                    lambda iid=item_id: sync._delete_legacy_item(iid, entry_type)
                                )
                            except Exception as e:
                                logger.warning(f"Failed to delete legacy {item_id}: {e}")
                    else:
                        failed_count += 1

                # Signal completion
                await progress_queue.put({
                    "type": "done",
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "results": results,
                })

            # Start migration task
            migration_task = asyncio.create_task(run_migration())

            # Forward progress updates to WebSocket
            try:
                while True:
                    # Get progress with timeout to check if task is done
                    try:
                        progress = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                        await websocket.send_json(progress)

                        if progress.get("type") == "done":
                            break
                    except asyncio.TimeoutError:
                        if migration_task.done():
                            # Check for any remaining items in queue
                            while not progress_queue.empty():
                                progress = await progress_queue.get()
                                await websocket.send_json(progress)
                            break
            except Exception as e:
                logger.error(f"Error forwarding progress: {e}")
                await websocket.send_json({"type": "error", "error": str(e)})

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass


@router.websocket("/ws/sync")
async def websocket_sync(websocket: WebSocket):
    """WebSocket endpoint for sync operations (download/upload) with real-time progress.

    Client sends JSON messages:
    - {"action": "download", "entry_type": "models"|"datasets", "item_ids": [...]}
    - {"action": "upload", "entry_type": "models"|"datasets", "item_ids": [...]}

    Server sends progress updates:
    - {"type": "start", "item_id": "...", "total_files": N, "total_size": M}
    - {"type": "downloading", "item_id": "...", "current_file": "...", "file_size": N, "bytes_transferred": M}
    - {"type": "downloaded", "item_id": "...", "current_file": "...", "files_done": M, "total_files": N}
    - {"type": "complete", "item_id": "...", "total_files": N, "total_size": M}
    - {"type": "error", "item_id": "...", "error": "..."}
    - {"type": "done", "success_count": N, "failed_count": M, "results": {...}}
    """
    await websocket.accept()

    try:
        while True:
            # Wait for sync request
            data = await websocket.receive_json()

            action = data.get("action")
            if action not in ("download", "upload"):
                await websocket.send_json({"type": "error", "error": "Unknown action. Use 'download' or 'upload'"})
                continue

            entry_type = data.get("entry_type", "models")
            item_ids = data.get("item_ids", [])

            if not item_ids:
                await websocket.send_json({"type": "error", "error": "No items specified"})
                continue

            # Get sync service
            sync = _get_sync_service()

            # Queue for progress updates from thread
            progress_queue: asyncio.Queue = asyncio.Queue()

            # Capture event loop for use in thread callback
            main_loop = asyncio.get_running_loop()

            def progress_callback(progress: dict):
                """Callback to put progress in queue (called from thread)."""
                asyncio.run_coroutine_threadsafe(
                    progress_queue.put(progress),
                    main_loop
                )

            async def run_sync():
                """Run sync operation in thread pool."""
                results = {}
                success_count = 0
                failed_count = 0

                loop = asyncio.get_event_loop()

                for item_id in item_ids:
                    # Run in thread pool to avoid blocking
                    if action == "download":
                        if entry_type == "models":
                            success, error = await loop.run_in_executor(
                                _executor,
                                lambda iid=item_id: sync.download_model_with_progress(
                                    iid, progress_callback
                                )
                            )
                        else:
                            success, error = await loop.run_in_executor(
                                _executor,
                                lambda iid=item_id: sync.download_dataset_with_progress(
                                    iid, progress_callback
                                )
                            )
                    else:  # upload
                        if entry_type == "models":
                            success, error = await loop.run_in_executor(
                                _executor,
                                lambda iid=item_id: sync.upload_model_with_progress(
                                    iid, progress_callback
                                )
                            )
                        else:
                            success, error = await loop.run_in_executor(
                                _executor,
                                lambda iid=item_id: sync.upload_dataset_with_progress(
                                    iid, progress_callback
                                )
                            )

                    results[item_id] = {"success": success, "error": error}
                    if success:
                        success_count += 1
                    else:
                        failed_count += 1

                # Signal completion
                await progress_queue.put({
                    "type": "done",
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "results": results,
                })

            # Start sync task
            sync_task = asyncio.create_task(run_sync())

            # Forward progress updates to WebSocket
            try:
                while True:
                    # Get progress with timeout to check if task is done
                    try:
                        progress = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                        await websocket.send_json(progress)

                        if progress.get("type") == "done":
                            break
                    except asyncio.TimeoutError:
                        if sync_task.done():
                            # Check for any remaining items in queue
                            while not progress_queue.empty():
                                progress = await progress_queue.get()
                                await websocket.send_json(progress)
                            break
            except Exception as e:
                logger.error(f"Error forwarding progress: {e}")
                await websocket.send_json({"type": "error", "error": str(e)})

    except WebSocketDisconnect:
        logger.info("WebSocket sync client disconnected")
    except Exception as e:
        logger.error(f"WebSocket sync error: {e}")
        try:
            await websocket.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass
