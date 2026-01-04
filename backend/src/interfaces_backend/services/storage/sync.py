"""R2 synchronization service for datasets and models."""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from interfaces_backend.models.storage import (
    DatasetMetadata,
    DataSource,
    ManifestEntry,
    ModelMetadata,
    SyncInfo,
)
from interfaces_backend.services.storage.hash import compute_directory_hash, compute_directory_size
from interfaces_backend.services.storage.manifest import ManifestManager

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SyncStatus:
    """Sync status for a dataset or model."""

    id: str
    source: DataSource
    local_exists: bool
    remote_exists: bool
    local_hash: Optional[str]
    remote_hash: Optional[str]
    local_size_bytes: int
    remote_size_bytes: int
    is_synced: bool
    needs_upload: bool
    needs_download: bool


class R2SyncService:
    """Service for syncing datasets and models with R2 storage."""

    def __init__(
        self,
        manifest_manager: ManifestManager,
        bucket: str,
        s3_manager: Optional["S3Manager"] = None,
        version: str = "",
    ):
        """Initialize sync service.

        Args:
            manifest_manager: The manifest manager instance
            bucket: R2 bucket name
            s3_manager: Optional S3Manager instance. If not provided, creates one.
            version: Optional version prefix (e.g., "v2"). If set, all paths will be prefixed.
        """
        self.manifest = manifest_manager
        self.bucket = bucket
        self.version = version
        self._s3: Optional["S3Manager"] = s3_manager

    def _get_prefix(self) -> str:
        """Get version prefix for paths."""
        return f"{self.version}/" if self.version else ""

    @property
    def s3(self) -> "S3Manager":
        """Lazy load S3Manager."""
        if self._s3 is None:
            try:
                from percus_ai.storage.s3 import S3Manager
                self._s3 = S3Manager()
            except ImportError:
                raise ImportError(
                    "percus_ai.storage.s3 not available. "
                    "Install with: pip install percus-ai[storage]"
                )
        return self._s3

    def _get_remote_path(self, entry_type: str, item_id: str) -> str:
        """Get the S3 path for a dataset or model."""
        prefix = self._get_prefix()
        return f"s3://{self.bucket}/{prefix}{entry_type}/{item_id}"

    def _get_remote_meta_path(self, entry_type: str, item_id: str) -> str:
        """Get the S3 path for metadata file."""
        prefix = self._get_prefix()
        return f"s3://{self.bucket}/{prefix}{entry_type}/{item_id}/.meta.json"

    def _fetch_remote_metadata(
        self, entry_type: str, item_id: str
    ) -> Optional[Dict]:
        """Fetch metadata from R2."""
        import tempfile

        s3_path = self._get_remote_meta_path(entry_type, item_id)
        try:
            objects = self.s3.list_objects(s3_path)
            if not objects:
                return None

            with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
                temp_path = f.name

            bucket, key = self.s3.parse_s3_path(s3_path)
            self.s3.client.download_file(bucket, key, temp_path)

            with open(temp_path) as f:
                data = json.load(f)

            os.unlink(temp_path)
            return data
        except Exception as e:
            logger.debug(f"Failed to fetch remote metadata for {item_id}: {e}")
            return None

    def _get_remote_info(self, entry_type: str, item_id: str) -> Tuple[bool, Optional[str], int]:
        """Get remote existence, hash, and size.

        Returns:
            Tuple of (exists, hash, size_bytes)
        """
        meta = self._fetch_remote_metadata(entry_type, item_id)
        if meta:
            sync_info = meta.get("sync", {})
            return True, sync_info.get("hash"), sync_info.get("size_bytes", 0)

        s3_path = self._get_remote_path(entry_type, item_id)
        objects = self.s3.list_objects(s3_path)
        if objects:
            total_size = sum(obj["Size"] for obj in objects)
            return True, None, total_size

        return False, None, 0

    # --- Dataset Sync ---

    def check_dataset_sync(self, dataset_id: str) -> Optional[SyncStatus]:
        """Check sync status for a dataset."""
        metadata = self.manifest.get_dataset(dataset_id)
        if not metadata:
            return None

        entry = self.manifest.manifest.datasets.get(dataset_id)
        if not entry:
            return None

        local_path = self.manifest.base_path / entry.path
        local_exists = local_path.exists()
        local_hash = compute_directory_hash(local_path) if local_exists else None
        local_size = compute_directory_size(local_path) if local_exists else 0

        remote_exists, remote_hash, remote_size = self._get_remote_info("datasets", dataset_id)

        is_synced = local_hash == remote_hash if (local_hash and remote_hash) else False
        needs_upload = local_exists and (not remote_exists or local_hash != remote_hash)
        needs_download = remote_exists and (not local_exists or local_hash != remote_hash)

        return SyncStatus(
            id=dataset_id,
            source=metadata.source,
            local_exists=local_exists,
            remote_exists=remote_exists,
            local_hash=local_hash,
            remote_hash=remote_hash,
            local_size_bytes=local_size,
            remote_size_bytes=remote_size,
            is_synced=is_synced,
            needs_upload=needs_upload,
            needs_download=needs_download,
        )

    def upload_dataset(self, dataset_id: str) -> bool:
        """Upload dataset to R2.

        Args:
            dataset_id: Dataset ID to upload

        Returns:
            True if successful
        """
        metadata = self.manifest.get_dataset(dataset_id)
        if not metadata:
            logger.error(f"Dataset not found: {dataset_id}")
            return False

        if metadata.source != DataSource.R2:
            logger.error(f"Cannot upload non-R2 dataset: {dataset_id}")
            return False

        entry = self.manifest.manifest.datasets.get(dataset_id)
        if not entry:
            return False

        local_path = self.manifest.base_path / entry.path
        if not local_path.exists():
            logger.error(f"Local path not found: {local_path}")
            return False

        s3_path = self._get_remote_path("datasets", dataset_id)

        try:
            new_hash = compute_directory_hash(local_path)
            new_size = compute_directory_size(local_path)

            metadata.sync.hash = new_hash
            metadata.sync.size_bytes = new_size
            metadata.sync.last_synced_at = _now_iso()
            self.manifest.update_dataset(metadata)

            uploaded = self.s3.upload_directory(str(local_path), s3_path)
            logger.info(f"Uploaded {uploaded} files for dataset {dataset_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to upload dataset {dataset_id}: {e}")
            return False

    def download_dataset(
        self,
        dataset_id: str,
        episodes: Optional[List[int]] = None,
        include_videos: bool = True,
    ) -> bool:
        """Download dataset from R2.

        Args:
            dataset_id: Dataset ID to download
            episodes: Specific episodes to download (None for all)
            include_videos: Include video files

        Returns:
            True if successful
        """
        entry = self.manifest.manifest.datasets.get(dataset_id)
        if not entry:
            remote_meta = self._fetch_remote_metadata("datasets", dataset_id)
            if not remote_meta:
                logger.error(f"Dataset not found locally or remotely: {dataset_id}")
                return False

            metadata = DatasetMetadata(**remote_meta)
            self.manifest.register_dataset(metadata)
            entry = self.manifest.manifest.datasets.get(dataset_id)

        local_path = self.manifest.base_path / entry.path
        s3_path = self._get_remote_path("datasets", dataset_id)

        try:
            if episodes is not None:
                downloaded = self._download_partial_dataset(
                    s3_path, local_path, episodes, include_videos
                )
            else:
                downloaded = self.s3.download_directory(s3_path, str(local_path))

            new_hash = compute_directory_hash(local_path)
            new_size = compute_directory_size(local_path)

            metadata = self.manifest.get_dataset(dataset_id)
            if metadata:
                metadata.sync.hash = new_hash
                metadata.sync.size_bytes = new_size
                metadata.sync.last_synced_at = _now_iso()
                self.manifest.update_dataset(metadata)

            logger.info(f"Downloaded {downloaded} files for dataset {dataset_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to download dataset {dataset_id}: {e}")
            return False

    def _download_partial_dataset(
        self,
        s3_path: str,
        local_path: Path,
        episodes: List[int],
        include_videos: bool,
    ) -> int:
        """Download specific episodes from dataset."""
        import tempfile

        bucket, prefix = self.s3.parse_s3_path(s3_path)
        objects = self.s3.list_objects(s3_path)

        episode_patterns = [f"episode_{ep:03d}" for ep in episodes]
        episode_patterns.extend([f"episode_{ep:06d}" for ep in episodes])

        downloaded = 0
        for obj in objects:
            key = obj["Key"]
            relative = key[len(prefix):].lstrip("/") if key.startswith(prefix) else key

            should_download = False

            if relative.startswith(".meta") or relative.startswith("meta/"):
                should_download = True
            elif any(pattern in relative for pattern in episode_patterns):
                if include_videos or not relative.startswith("videos/"):
                    should_download = True

            if should_download:
                local_file = local_path / relative
                local_file.parent.mkdir(parents=True, exist_ok=True)
                self.s3.client.download_file(bucket, key, str(local_file))
                downloaded += 1

        return downloaded

    # --- Model Sync ---

    def check_model_sync(self, model_id: str) -> Optional[SyncStatus]:
        """Check sync status for a model."""
        metadata = self.manifest.get_model(model_id)
        if not metadata:
            return None

        entry = self.manifest.manifest.models.get(model_id)
        if not entry:
            return None

        local_path = self.manifest.base_path / entry.path
        local_exists = local_path.exists()
        local_hash = compute_directory_hash(local_path) if local_exists else None
        local_size = compute_directory_size(local_path) if local_exists else 0

        remote_exists, remote_hash, remote_size = self._get_remote_info("models", model_id)

        is_synced = local_hash == remote_hash if (local_hash and remote_hash) else False
        needs_upload = local_exists and (not remote_exists or local_hash != remote_hash)
        needs_download = remote_exists and (not local_exists or local_hash != remote_hash)

        return SyncStatus(
            id=model_id,
            source=metadata.source,
            local_exists=local_exists,
            remote_exists=remote_exists,
            local_hash=local_hash,
            remote_hash=remote_hash,
            local_size_bytes=local_size,
            remote_size_bytes=remote_size,
            is_synced=is_synced,
            needs_upload=needs_upload,
            needs_download=needs_download,
        )

    def upload_model(self, model_id: str) -> bool:
        """Upload model to R2."""
        metadata = self.manifest.get_model(model_id)
        if not metadata:
            logger.error(f"Model not found: {model_id}")
            return False

        if metadata.source != DataSource.R2:
            logger.error(f"Cannot upload non-R2 model: {model_id}")
            return False

        entry = self.manifest.manifest.models.get(model_id)
        if not entry:
            return False

        local_path = self.manifest.base_path / entry.path
        if not local_path.exists():
            logger.error(f"Local path not found: {local_path}")
            return False

        s3_path = self._get_remote_path("models", model_id)

        try:
            new_hash = compute_directory_hash(local_path)
            new_size = compute_directory_size(local_path)

            metadata.sync.hash = new_hash
            metadata.sync.size_bytes = new_size
            metadata.sync.last_synced_at = _now_iso()
            self.manifest.update_model(metadata)

            uploaded = self.s3.upload_directory(str(local_path), s3_path)
            logger.info(f"Uploaded {uploaded} files for model {model_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to upload model {model_id}: {e}")
            return False

    def download_model(self, model_id: str) -> bool:
        """Download model from R2."""
        entry = self.manifest.manifest.models.get(model_id)
        if not entry:
            remote_meta = self._fetch_remote_metadata("models", model_id)
            if not remote_meta:
                logger.error(f"Model not found locally or remotely: {model_id}")
                return False

            metadata = ModelMetadata(**remote_meta)
            self.manifest.register_model(metadata)
            entry = self.manifest.manifest.models.get(model_id)

        local_path = self.manifest.base_path / entry.path
        s3_path = self._get_remote_path("models", model_id)

        try:
            downloaded = self.s3.download_directory(s3_path, str(local_path))

            new_hash = compute_directory_hash(local_path)
            new_size = compute_directory_size(local_path)

            metadata = self.manifest.get_model(model_id)
            if metadata:
                metadata.sync.hash = new_hash
                metadata.sync.size_bytes = new_size
                metadata.sync.last_synced_at = _now_iso()
                self.manifest.update_model(metadata)

            logger.info(f"Downloaded {downloaded} files for model {model_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to download model {model_id}: {e}")
            return False

    # --- Manifest Sync ---

    def sync_manifest_to_r2(self) -> bool:
        """Upload local manifest to R2."""
        try:
            prefix = self._get_prefix()
            manifest_s3_path = f"s3://{self.bucket}/{prefix}.manifest.json"
            bucket, key = self.s3.parse_s3_path(manifest_s3_path)

            import tempfile
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as f:
                json.dump(self.manifest.manifest.model_dump(), f, indent=2, ensure_ascii=False)
                temp_path = f.name

            self.s3.client.upload_file(temp_path, bucket, key)
            os.unlink(temp_path)

            logger.info("Synced manifest to R2")
            return True
        except Exception as e:
            logger.error(f"Failed to sync manifest to R2: {e}")
            return False

    def sync_manifest_from_r2(self, merge: bool = True) -> bool:
        """Download manifest from R2.

        Args:
            merge: If True, merge with local manifest. If False, replace.

        Returns:
            True if successful
        """
        try:
            prefix = self._get_prefix()
            manifest_s3_path = f"s3://{self.bucket}/{prefix}.manifest.json"
            objects = self.s3.list_objects(manifest_s3_path)
            if not objects:
                logger.info("No remote manifest found")
                return True

            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
                temp_path = f.name

            bucket, key = self.s3.parse_s3_path(manifest_s3_path)
            self.s3.client.download_file(bucket, key, temp_path)

            with open(temp_path) as f:
                remote_data = json.load(f)
            os.unlink(temp_path)

            from interfaces_backend.models.storage import Manifest
            remote_manifest = Manifest(**remote_data)

            if merge:
                self._merge_manifests(remote_manifest)
            else:
                self.manifest._manifest = remote_manifest
                self.manifest.save()

            logger.info("Synced manifest from R2")
            return True
        except Exception as e:
            logger.error(f"Failed to sync manifest from R2: {e}")
            return False

    def _merge_manifests(self, remote: "Manifest") -> None:
        """Merge remote manifest into local, preferring newer entries."""
        local = self.manifest.manifest

        for dataset_id, remote_entry in remote.datasets.items():
            if dataset_id not in local.datasets:
                local.datasets[dataset_id] = remote_entry
            else:
                local_meta = self.manifest.get_dataset(dataset_id)
                if local_meta:
                    remote_meta_data = self._fetch_remote_metadata("datasets", dataset_id)
                    if remote_meta_data:
                        remote_updated = remote_meta_data.get("updated_at", "")
                        if remote_updated > local_meta.updated_at:
                            local.datasets[dataset_id] = remote_entry

        for model_id, remote_entry in remote.models.items():
            if model_id not in local.models:
                local.models[model_id] = remote_entry
            else:
                local_meta = self.manifest.get_model(model_id)
                if local_meta:
                    remote_meta_data = self._fetch_remote_metadata("models", model_id)
                    if remote_meta_data:
                        remote_updated = remote_meta_data.get("updated_at", "")
                        if remote_updated > local_meta.updated_at:
                            local.models[model_id] = remote_entry

        for project_id, remote_entry in remote.projects.items():
            if project_id not in local.projects:
                local.projects[project_id] = remote_entry

        local.last_updated = _now_iso()
        self.manifest.save()
