import asyncio
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")

from interfaces_backend.services.dataset_lifecycle import DatasetLifecycle


class _FakeSyncDownloaded:
    async def ensure_model_local(self, _model_id, auto_download=True, progress_callback=None):
        assert auto_download is True
        assert progress_callback is not None
        progress_callback({"type": "start", "total_files": 4, "total_size": 4000})
        progress_callback({
            "type": "progress",
            "current_file": "weights.safetensors",
            "files_done": 2,
            "total_files": 4,
            "bytes_done_total": 2500,
            "total_size": 4000,
        })
        progress_callback({"type": "complete", "total_files": 4, "total_size": 4000})
        return SimpleNamespace(success=True, message="Downloaded", skipped=False)


class _FakeSyncCacheHit:
    async def ensure_model_local(self, _model_id, auto_download=True, progress_callback=None):
        assert auto_download is True
        assert progress_callback is not None
        return SimpleNamespace(success=True, message="Cache hit", skipped=True)


class _FakeSyncFailure:
    async def ensure_model_local(self, _model_id, auto_download=True, progress_callback=None):
        assert auto_download is True
        assert progress_callback is not None
        return SimpleNamespace(success=False, message="not found", skipped=False)


def test_ensure_model_local_tracks_download_progress():
    lifecycle = DatasetLifecycle()
    lifecycle._sync = _FakeSyncDownloaded()

    asyncio.run(lifecycle.ensure_model_local("model-1"))
    status = lifecycle.get_model_sync_status()

    assert status.status == "completed"
    assert status.active is False
    assert status.progress_percent == 100.0
    assert status.total_files == 4
    assert status.files_done == 4
    assert status.total_bytes == 4000
    assert status.transferred_bytes == 4000
    assert status.error is None


def test_ensure_model_local_marks_error_on_failure():
    lifecycle = DatasetLifecycle()
    lifecycle._sync = _FakeSyncFailure()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(lifecycle.ensure_model_local("model-missing"))

    assert exc_info.value.status_code == 404
    status = lifecycle.get_model_sync_status()
    assert status.status == "error"
    assert status.active is False
    assert status.error == "not found"


def test_ensure_model_local_marks_cache_hit_completed():
    lifecycle = DatasetLifecycle()
    lifecycle._sync = _FakeSyncCacheHit()

    asyncio.run(lifecycle.ensure_model_local("model-cache"))
    status = lifecycle.get_model_sync_status()

    assert status.status == "completed"
    assert status.active is False
    assert status.progress_percent == 100.0
    assert status.message == "ローカルキャッシュを利用しました。"


def test_ensure_model_local_emits_sync_status_callback():
    lifecycle = DatasetLifecycle()
    lifecycle._sync = _FakeSyncDownloaded()
    updates = []

    def _callback(status):
        updates.append(status.status)

    asyncio.run(lifecycle.ensure_model_local("model-2", sync_status_callback=_callback))

    assert updates[0] == "checking"
    assert "syncing" in updates
    assert updates[-1] == "completed"
