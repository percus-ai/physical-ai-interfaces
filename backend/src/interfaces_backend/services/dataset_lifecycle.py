"""Dataset DB record management and R2 upload.

Consolidates dataset-related logic previously duplicated in
recording.py and inference.py.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import yaml
from fastapi import HTTPException

from percus_ai.db import get_supabase_async_client, upsert_with_owner
from percus_ai.storage.paths import get_datasets_dir, get_user_config_path
from percus_ai.storage.r2_db_sync import R2DBSyncService

logger = logging.getLogger(__name__)


class DatasetLifecycle:
    """Manages dataset DB records and R2 uploads."""

    def __init__(self) -> None:
        self._sync: R2DBSyncService | None = None

    # -- DB operations --------------------------------------------------------

    async def upsert_record(
        self,
        dataset_id: str,
        dataset_name: str,
        task: str,
        profile_snapshot: Optional[dict],
        status: str,
        dataset_type: str = "recorded",
    ) -> None:
        """Insert or update a dataset record in the datasets table."""
        payload = {
            "id": dataset_id,
            "name": dataset_name,
            "dataset_type": dataset_type,
            "source": "local",
            "status": status,
            "task_detail": task,
            "profile_instance_id": None,
            "profile_snapshot": profile_snapshot,
        }
        await upsert_with_owner("datasets", "id", payload)

    async def update_stats(self, dataset_id: str) -> None:
        """Read local dataset metadata and update episode count / size in DB."""
        dataset_root = get_datasets_dir() / dataset_id
        if not dataset_root.exists():
            return

        episode_count = 0
        meta_path = dataset_root / "meta" / "info.json"
        if meta_path.exists():
            try:
                info = json.loads(meta_path.read_text(encoding="utf-8"))
                episode_count = int(info.get("total_episodes") or 0)
            except Exception as exc:
                logger.warning("Failed to read dataset info.json for %s: %s", dataset_id, exc)
        else:
            try:
                from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata

                meta = LeRobotDatasetMetadata(dataset_id, root=dataset_root)
                episode_count = int(meta.total_episodes)
            except Exception as exc:
                logger.warning("Failed to read dataset metadata for %s: %s", dataset_id, exc)

        size_bytes = sum(p.stat().st_size for p in dataset_root.rglob("*") if p.is_file())
        payload = {
            "id": dataset_id,
            "episode_count": episode_count,
            "size_bytes": size_bytes,
            "status": "active",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await upsert_with_owner("datasets", "id", payload)

    async def mark_active(self, dataset_id: str) -> None:
        """Set datasets.status to 'active'."""
        client = await get_supabase_async_client()
        await (
            client.table("datasets")
            .update(
                {
                    "status": "active",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", dataset_id)
            .execute()
        )

    # -- R2 upload ------------------------------------------------------------

    async def auto_upload(self, dataset_id: str) -> None:
        """Upload dataset to R2 if auto-upload is enabled in user config."""
        user_config = self._load_user_config()
        if not user_config.get("auto_upload_after_recording", True):
            logger.info("Auto-upload disabled by user config; skipping for %s", dataset_id)
            return
        try:
            await self._get_sync_service().upload_dataset_with_progress(dataset_id, None)
            logger.info("Auto-upload completed for dataset %s", dataset_id)
        except Exception:
            logger.error("Auto-upload failed for dataset %s", dataset_id, exc_info=True)

    async def ensure_model_local(self, model_id: str) -> None:
        """Download a model from R2 if not cached locally."""
        sync_result = await self._get_sync_service().ensure_model_local(
            model_id, auto_download=True
        )
        if not sync_result.success:
            raise HTTPException(
                status_code=404, detail=f"Model not available: {sync_result.message}"
            )

    # -- internal helpers -----------------------------------------------------

    def _load_user_config(self) -> dict:
        path = get_user_config_path()
        if not path.exists():
            return {"auto_upload_after_recording": True}
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        sync = raw.get("sync", {})
        return {"auto_upload_after_recording": sync.get("auto_upload_after_recording", True)}

    def _get_sync_service(self) -> R2DBSyncService:
        if self._sync is None:
            self._sync = R2DBSyncService()
        return self._sync


# -- singleton ----------------------------------------------------------------

_lifecycle: DatasetLifecycle | None = None


def get_dataset_lifecycle() -> DatasetLifecycle:
    global _lifecycle
    if _lifecycle is None:
        _lifecycle = DatasetLifecycle()
    return _lifecycle
