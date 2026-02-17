import asyncio
import os
from types import SimpleNamespace

from fastapi import HTTPException

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")

import interfaces_backend.services.recording_session as recording_session
from interfaces_backend.services.recording_session import RecordingSessionManager
from interfaces_backend.services.session_manager import SessionState


class _FakeRecorder:
    def __init__(self):
        self.ensure_running_called = False
        self.stop_called = False
        self.status_payload = {"state": "recording", "dataset_id": "session-1"}

    def ensure_running(self):
        self.ensure_running_called = True

    def start(self, payload):
        return {"success": True, "message": "ok", "payload": payload}

    def status(self):
        return self.status_payload

    def stop(self, *, save_current=True):
        self.stop_called = True
        return {"success": True, "message": "stopped", "save_current": save_current}

    def pause(self):
        return {"success": True, "message": "paused"}

    def resume(self):
        return {"success": True, "message": "resumed"}


class _FakeDataset:
    def __init__(self):
        self.upserts = []
        self.updated = []
        self.uploaded = []

    async def upsert_record(self, **kwargs):
        self.upserts.append(kwargs)

    async def update_stats(self, dataset_id):
        self.updated.append(dataset_id)

    async def auto_upload(self, dataset_id):
        self.uploaded.append(dataset_id)


def _install_fake_base_stop(monkeypatch):
    async def fake_base_stop(self, session_id: str, **kwargs):
        with self._lock:
            state = self._sessions.pop(session_id, None)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        state.status = "stopped"
        return state

    monkeypatch.setattr(recording_session.BaseSessionManager, "stop", fake_base_stop)


def _build_manager(recorder, dataset):
    manager = RecordingSessionManager(recorder=recorder, dataset=dataset)
    manager._sessions["session-1"] = SessionState(
        id="session-1",
        kind="recording",
        profile=SimpleNamespace(name="profile-a", snapshot={"raw": {}}),
        extras={
            "dataset_name": "dataset-a",
            "task": "pick-place",
            "recorder_payload": {
                "dataset_id": "session-1",
                "cameras": [{"name": "cam_top", "topic": "/top_camera/image_raw/compressed"}],
            },
            "recording_started": True,
        },
    )
    return manager


def test_stop_completed_recorder_still_runs_auto_upload(monkeypatch):
    _install_fake_base_stop(monkeypatch)
    recorder = _FakeRecorder()
    recorder.status_payload = {"state": "completed", "dataset_id": "session-1"}
    dataset = _FakeDataset()
    manager = _build_manager(recorder, dataset)

    state = asyncio.run(manager.stop("session-1"))

    assert recorder.stop_called is False
    assert dataset.updated == ["session-1"]
    assert dataset.uploaded == ["session-1"]
    assert state.extras["recorder_result"]["message"] == "Recorder already finalized"


def test_completion_watcher_triggers_auto_upload(monkeypatch):
    _install_fake_base_stop(monkeypatch)

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(recording_session.asyncio, "sleep", fake_sleep)

    recorder = _FakeRecorder()
    recorder.status_payload = {"state": "completed", "dataset_id": "session-1"}
    dataset = _FakeDataset()
    manager = _build_manager(recorder, dataset)

    asyncio.run(manager._watch_completion("session-1"))

    assert recorder.stop_called is False
    assert dataset.updated == ["session-1"]
    assert dataset.uploaded == ["session-1"]
    assert manager.status("session-1") is None
