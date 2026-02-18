"""Dataset DB record management and R2 upload.

Consolidates dataset-related logic previously duplicated in
recording.py and inference.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Callable, Optional

import yaml
from fastapi import HTTPException
from supabase import create_async_client
from supabase._async.client import AsyncClient

from interfaces_backend.models.inference import InferenceModelSyncStatus
from interfaces_backend.services.realtime_events import get_realtime_event_bus
from percus_ai.db import get_supabase_async_client, upsert_with_owner
from percus_ai.storage.paths import get_datasets_dir, get_user_config_path
from percus_ai.storage.r2_db_sync import R2DBSyncService

logger = logging.getLogger(__name__)
UPLOAD_TOPIC = "recording.upload"


class DatasetLifecycle:
    """Manages dataset DB records and R2 uploads."""

    def __init__(self) -> None:
        self._sync: R2DBSyncService | None = None
        self._model_sync_lock = threading.Lock()
        self._model_sync_status = InferenceModelSyncStatus()
        self._dataset_upload_lock = threading.Lock()
        self._dataset_upload_status: dict[str, dict] = {}
        self._service_client: AsyncClient | None = None
        self._service_client_lock = asyncio.Lock()

    async def _get_internal_db_client(self) -> AsyncClient:
        """Return a DB client that is safe for long-running background tasks."""
        supabase_url = os.environ.get("SUPABASE_URL")
        service_key = os.environ.get("SUPABASE_SECRET_KEY")
        if supabase_url and service_key:
            if self._service_client is not None:
                return self._service_client
            async with self._service_client_lock:
                if self._service_client is None:
                    self._service_client = await create_async_client(supabase_url, service_key)
                return self._service_client
        return await get_supabase_async_client()

    # -- DB operations --------------------------------------------------------

    async def upsert_record(
        self,
        dataset_id: str,
        dataset_name: str,
        task: str,
        profile_snapshot: Optional[dict],
        status: str,
        target_total_episodes: int | None = None,
        episode_time_s: float | None = None,
        reset_time_s: float | None = None,
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
        if target_total_episodes is not None:
            payload["target_total_episodes"] = target_total_episodes
        if episode_time_s is not None:
            payload["episode_time_s"] = episode_time_s
        if reset_time_s is not None:
            payload["reset_time_s"] = reset_time_s
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
            "episode_count": episode_count,
            "size_bytes": size_bytes,
            "status": "active",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        client = await self._get_internal_db_client()
        await client.table("datasets").update(payload).eq("id", dataset_id).execute()

    async def mark_active(self, dataset_id: str) -> None:
        """Set datasets.status to 'active'."""
        client = await self._get_internal_db_client()
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
            self._set_dataset_upload_status(
                dataset_id=dataset_id,
                status="disabled",
                phase="disabled",
                progress_percent=100.0,
                message="Auto-upload is disabled by user config.",
                files_done=0,
                total_files=0,
                current_file=None,
                error=None,
            )
            return

        ok, error = await self._upload_dataset_with_status(
            dataset_id=dataset_id,
            running_message="Uploading dataset to R2...",
        )
        if ok:
            logger.info("Auto-upload completed for dataset %s", dataset_id)
            return
        logger.error("Auto-upload failed for dataset %s: %s", dataset_id, error)

    async def reupload(self, dataset_id: str) -> tuple[bool, str]:
        """Upload a dataset to R2 regardless of auto-upload user settings."""
        return await self._upload_dataset_with_status(
            dataset_id=dataset_id,
            running_message="Re-uploading dataset to R2...",
        )

    def _build_dataset_upload_progress_callback(
        self,
        *,
        dataset_id: str,
        running_message: str,
    ) -> Callable[[dict], None]:
        def upload_progress(message: dict) -> None:
            event_type = str(message.get("type") or "")
            files_done = self._to_int(message.get("files_done"))
            total_files = self._to_int(message.get("total_files"))
            current_file_raw = message.get("current_file")
            current_file = str(current_file_raw) if current_file_raw else None
            progress_percent = 0.0
            if total_files > 0:
                progress_percent = round(min(max(files_done / total_files, 0.0), 1.0) * 100.0, 2)

            if event_type == "start":
                self._set_dataset_upload_status(
                    dataset_id=dataset_id,
                    status="running",
                    phase="starting",
                    progress_percent=0.0,
                    message=running_message,
                    files_done=0,
                    total_files=total_files,
                    current_file=None,
                    error=None,
                )
                return

            if event_type in {"uploading", "progress", "uploaded"}:
                self._set_dataset_upload_status(
                    dataset_id=dataset_id,
                    status="running",
                    phase="uploading",
                    progress_percent=progress_percent,
                    message=running_message,
                    files_done=files_done,
                    total_files=total_files,
                    current_file=current_file,
                    error=None,
                )
                return

            if event_type == "complete":
                self._set_dataset_upload_status(
                    dataset_id=dataset_id,
                    status="completed",
                    phase="completed",
                    progress_percent=100.0,
                    message="Upload completed.",
                    files_done=total_files,
                    total_files=total_files,
                    current_file=None,
                    error=None,
                )
                return

            if event_type == "error":
                self._set_dataset_upload_status(
                    dataset_id=dataset_id,
                    status="failed",
                    phase="failed",
                    progress_percent=progress_percent,
                    message="Upload failed.",
                    files_done=files_done,
                    total_files=total_files,
                    current_file=current_file,
                    error=str(message.get("error") or "unknown error"),
                )

        return upload_progress

    async def _upload_dataset_with_status(
        self,
        *,
        dataset_id: str,
        running_message: str,
    ) -> tuple[bool, str]:
        self._set_dataset_upload_status(
            dataset_id=dataset_id,
            status="running",
            phase="starting",
            progress_percent=0.0,
            message=running_message,
            files_done=0,
            total_files=0,
            current_file=None,
            error=None,
        )
        upload_progress = self._build_dataset_upload_progress_callback(
            dataset_id=dataset_id,
            running_message=running_message,
        )

        try:
            ok, error = await self._get_sync_service().upload_dataset_with_progress(
                dataset_id,
                upload_progress,
            )
            if ok:
                self._set_dataset_upload_status(
                    dataset_id=dataset_id,
                    status="completed",
                    phase="completed",
                    progress_percent=100.0,
                    message="Upload completed.",
                    current_file=None,
                    error=None,
                )
                return True, ""

            self._set_dataset_upload_status(
                dataset_id=dataset_id,
                status="failed",
                phase="failed",
                message="Upload failed.",
                error=error,
            )
            return False, str(error or "unknown error")
        except Exception:
            logger.error("Dataset upload failed for %s", dataset_id, exc_info=True)
            self._set_dataset_upload_status(
                dataset_id=dataset_id,
                status="failed",
                phase="failed",
                message="Upload failed.",
                error="unexpected error",
            )
            return False, "unexpected error"

    def get_dataset_upload_status(self, dataset_id: str) -> dict:
        with self._dataset_upload_lock:
            snapshot = self._dataset_upload_status.get(dataset_id)
            if snapshot is None:
                return {
                    "dataset_id": dataset_id,
                    "status": "idle",
                    "phase": "idle",
                    "progress_percent": 0.0,
                    "message": "No upload activity.",
                    "files_done": 0,
                    "total_files": 0,
                    "current_file": None,
                    "error": None,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            return dict(snapshot)

    async def ensure_model_local(
        self,
        model_id: str,
        sync_status_callback: Optional[Callable[[InferenceModelSyncStatus], None]] = None,
    ) -> None:
        """Download a model from R2 if not cached locally."""
        status_snapshot = self._set_model_sync_status(
            active=True,
            status="checking",
            model_id=model_id,
            message="モデルの同期状態を確認しています...",
            progress_percent=0.0,
            total_files=0,
            files_done=0,
            total_bytes=0,
            transferred_bytes=0,
            current_file=None,
            error=None,
        )
        if sync_status_callback is not None:
            sync_status_callback(status_snapshot)

        def on_sync_progress(progress: dict) -> None:
            event_type = str(progress.get("type") or "")
            total_files = self._to_int(progress.get("total_files"))
            files_done = self._to_int(progress.get("files_done"))
            total_bytes = self._to_int(progress.get("total_size"))
            transferred_bytes = self._to_int(
                progress.get("bytes_done_total", progress.get("bytes_transferred"))
            )
            current_file = progress.get("current_file")
            if event_type == "start":
                snapshot = self._set_model_sync_status(
                    active=True,
                    status="syncing",
                    message="モデルをクラウドから同期中です...",
                    total_files=total_files,
                    files_done=0,
                    total_bytes=total_bytes,
                    transferred_bytes=0,
                    current_file=None,
                    progress_percent=0.0,
                    error=None,
                )
                if sync_status_callback is not None:
                    sync_status_callback(snapshot)
                return
            if event_type in {"downloading", "progress", "downloaded"}:
                progress_percent = self._compute_progress_percent(
                    total_files=total_files,
                    files_done=files_done,
                    total_bytes=total_bytes,
                    transferred_bytes=transferred_bytes,
                )
                snapshot = self._set_model_sync_status(
                    active=True,
                    status="syncing",
                    message="モデルをクラウドから同期中です...",
                    total_files=total_files,
                    files_done=files_done,
                    total_bytes=total_bytes,
                    transferred_bytes=transferred_bytes,
                    current_file=str(current_file) if current_file else None,
                    progress_percent=progress_percent,
                    error=None,
                )
                if sync_status_callback is not None:
                    sync_status_callback(snapshot)
                return
            if event_type == "complete":
                snapshot = self._set_model_sync_status(
                    active=False,
                    status="completed",
                    message="モデル同期が完了しました。",
                    progress_percent=100.0,
                    files_done=total_files,
                    total_files=total_files,
                    transferred_bytes=total_bytes,
                    total_bytes=total_bytes,
                    current_file=None,
                    error=None,
                )
                if sync_status_callback is not None:
                    sync_status_callback(snapshot)
                return
            if event_type == "error":
                snapshot = self._set_model_sync_status(
                    active=False,
                    status="error",
                    message="モデル同期に失敗しました。",
                    error=str(progress.get("error") or "unknown error"),
                )
                if sync_status_callback is not None:
                    sync_status_callback(snapshot)

        sync_result = await self._get_sync_service().ensure_model_local(
            model_id,
            auto_download=True,
            progress_callback=on_sync_progress,
        )
        if not sync_result.success:
            snapshot = self._set_model_sync_status(
                active=False,
                status="error",
                message="モデル同期に失敗しました。",
                error=sync_result.message,
            )
            if sync_status_callback is not None:
                sync_status_callback(snapshot)
            raise HTTPException(
                status_code=404, detail=f"Model not available: {sync_result.message}"
            )
        if sync_result.skipped:
            snapshot = self._set_model_sync_status(
                active=False,
                status="completed",
                message="ローカルキャッシュを利用しました。",
                progress_percent=100.0,
                current_file=None,
                error=None,
            )
            if sync_status_callback is not None:
                sync_status_callback(snapshot)
        else:
            snapshot = self._set_model_sync_status(
                active=False,
                status="completed",
                message="モデル同期が完了しました。",
                progress_percent=100.0,
                current_file=None,
                error=None,
            )
            if sync_status_callback is not None:
                sync_status_callback(snapshot)

    def get_model_sync_status(self) -> InferenceModelSyncStatus:
        with self._model_sync_lock:
            return self._model_sync_status.model_copy(deep=True)

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

    @staticmethod
    def _to_int(value: object) -> int:
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _compute_progress_percent(
        *,
        total_files: int,
        files_done: int,
        total_bytes: int,
        transferred_bytes: int,
    ) -> float:
        if total_bytes > 0:
            return round(min(max(transferred_bytes / total_bytes, 0.0), 1.0) * 100, 2)
        if total_files > 0:
            return round(min(max(files_done / total_files, 0.0), 1.0) * 100, 2)
        return 0.0

    def _set_model_sync_status(self, **updates: object) -> InferenceModelSyncStatus:
        with self._model_sync_lock:
            payload = self._model_sync_status.model_dump(mode="python")
            payload.update(updates)
            progress_percent = payload.get("progress_percent")
            try:
                normalized = float(progress_percent or 0.0)
            except (TypeError, ValueError):
                normalized = 0.0
            payload["progress_percent"] = min(max(normalized, 0.0), 100.0)
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._model_sync_status = InferenceModelSyncStatus.model_validate(payload)
            return self._model_sync_status.model_copy(deep=True)

    def _set_dataset_upload_status(self, *, dataset_id: str, **updates: object) -> dict:
        with self._dataset_upload_lock:
            payload = self._dataset_upload_status.get(dataset_id, {}).copy()
            payload.setdefault("dataset_id", dataset_id)
            payload.setdefault("status", "idle")
            payload.setdefault("phase", "idle")
            payload.setdefault("progress_percent", 0.0)
            payload.setdefault("message", "")
            payload.setdefault("files_done", 0)
            payload.setdefault("total_files", 0)
            payload.setdefault("current_file", None)
            payload.setdefault("error", None)
            payload.update(updates)
            progress_percent = payload.get("progress_percent")
            try:
                normalized = float(progress_percent or 0.0)
            except (TypeError, ValueError):
                normalized = 0.0
            payload["progress_percent"] = min(max(normalized, 0.0), 100.0)
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._dataset_upload_status[dataset_id] = payload
            snapshot = dict(payload)
        get_realtime_event_bus().publish_threadsafe(UPLOAD_TOPIC, dataset_id, snapshot)
        return snapshot


# -- singleton ----------------------------------------------------------------

_lifecycle: DatasetLifecycle | None = None


def get_dataset_lifecycle() -> DatasetLifecycle:
    global _lifecycle
    if _lifecycle is None:
        _lifecycle = DatasetLifecycle()
    return _lifecycle
