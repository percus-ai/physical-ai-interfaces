import asyncio
import os
from types import SimpleNamespace

from fastapi import HTTPException

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")

import interfaces_backend.services.recording_session as recording_session
import interfaces_backend.services.session_manager as session_manager
from interfaces_backend.services.recording_session import RecordingSessionManager
from interfaces_backend.services.session_manager import SessionState


class _FakeRecorder:
    def __init__(self):
        self.ensure_running_called = False
        self.stop_called = False
        self.start_payloads = []
        self.start_result = {"success": True, "message": "ok"}
        self.status_payload = {"state": "recording", "dataset_id": "session-1"}
        self.status_exception = None

    def ensure_running(self):
        self.ensure_running_called = True

    def build_cameras(self, _snapshot):
        return [{"name": "cam_top", "topic": "/top_camera/image_raw/compressed"}]

    def start(self, payload):
        self.start_payloads.append(payload)
        result = dict(self.start_result)
        result.setdefault("payload", payload)
        return result

    def status(self):
        if self.status_exception is not None:
            raise self.status_exception
        return self.status_payload

    def stop(self, *, save_current=True):
        self.stop_called = True
        return {"success": True, "message": "stopped", "save_current": save_current}

    def wait_until_finalized(self, dataset_id: str, timeout_s: float = 30.0, poll_interval_s: float = 0.5):
        _ = (dataset_id, timeout_s, poll_interval_s)
        return self.status_payload

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


def test_stop_raises_when_recorder_stays_active(monkeypatch):
    _install_fake_base_stop(monkeypatch)
    recorder = _FakeRecorder()
    recorder.status_payload = {"state": "recording", "dataset_id": "session-1"}
    dataset = _FakeDataset()
    manager = _build_manager(recorder, dataset)

    try:
        asyncio.run(manager.stop("session-1"))
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 500
        assert "timed out before finalize" in str(exc.detail)

    assert dataset.updated == []
    assert dataset.uploaded == []


def test_start_is_idempotent_when_recorder_already_active_same_dataset():
    recorder = _FakeRecorder()
    recorder.status_payload = {"state": "recording", "dataset_id": "session-1"}
    dataset = _FakeDataset()
    manager = _build_manager(recorder, dataset)

    state = asyncio.run(manager.start("session-1"))

    assert recorder.ensure_running_called is True
    assert recorder.start_payloads == []
    assert state.extras["recorder_result"]["message"] == "Recorder already active"
    assert dataset.upserts[-1]["status"] == "recording"


def test_start_rejects_when_other_session_is_active():
    recorder = _FakeRecorder()
    recorder.status_payload = {"state": "recording", "dataset_id": "session-2"}
    dataset = _FakeDataset()
    manager = _build_manager(recorder, dataset)

    try:
        asyncio.run(manager.start("session-1"))
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 409
        assert "another session" in str(exc.detail)

    assert recorder.start_payloads == []
    assert dataset.upserts == []


def test_start_handles_race_when_recorder_reports_already_active():
    class _RaceRecorder(_FakeRecorder):
        def __init__(self):
            super().__init__()
            self.start_result = {"success": False, "message": "session already active"}
            self._status_calls = 0

        def status(self):
            self._status_calls += 1
            if self._status_calls >= 2:
                return {"state": "warming", "dataset_id": "session-1"}
            return {"state": "idle", "dataset_id": ""}

    recorder = _RaceRecorder()
    dataset = _FakeDataset()
    manager = _build_manager(recorder, dataset)

    state = asyncio.run(manager.start("session-1"))

    assert recorder.start_payloads
    assert state.extras["recorder_result"]["success"] is True
    assert state.extras["recorder_result"]["message"] == "Recorder already active"
    assert dataset.upserts[-1]["status"] == "recording"


def test_create_includes_profile_topic_suffixes(monkeypatch):
    async def fake_resolve_profile(self, _profile):
        return SimpleNamespace(name="profile-a", snapshot={"profile": {}})

    async def fake_save_session_profile_binding(**_kwargs):
        return None

    monkeypatch.setattr(RecordingSessionManager, "_resolve_profile", fake_resolve_profile)
    monkeypatch.setattr(session_manager, "get_current_user_id", lambda: "user-1")
    monkeypatch.setattr(
        session_manager,
        "save_session_profile_binding",
        fake_save_session_profile_binding,
    )
    monkeypatch.setattr(recording_session, "extract_arm_namespaces", lambda _snapshot: ["follower_arm"])
    monkeypatch.setattr(
        recording_session,
        "extract_recorder_topic_suffixes",
        lambda _snapshot, arm_namespaces: {
            "state_topic_suffix": "joint_states_single",
            "action_topic_suffix": "joint_ctrl_single",
        },
    )

    recorder = _FakeRecorder()
    dataset = _FakeDataset()
    manager = RecordingSessionManager(recorder=recorder, dataset=dataset)

    state = asyncio.run(
        manager.create(
            session_id="session-1",
            dataset_name="dataset-a",
            task="pick-place",
            num_episodes=5,
            target_total_episodes=5,
            episode_time_s=60.0,
            reset_time_s=10.0,
        )
    )

    payload = state.extras["recorder_payload"]
    assert payload["state_topic_suffix"] == "joint_states_single"
    assert payload["action_topic_suffix"] == "joint_ctrl_single"


def test_create_raises_when_action_suffix_unresolved(monkeypatch):
    async def fake_resolve_profile(self, _profile):
        return SimpleNamespace(
            name="profile-a",
            source_path="/tmp/profile-a.yaml",
            snapshot={"profile": {}},
        )

    async def fake_save_session_profile_binding(**_kwargs):
        return None

    monkeypatch.setattr(RecordingSessionManager, "_resolve_profile", fake_resolve_profile)
    monkeypatch.setattr(session_manager, "get_current_user_id", lambda: "user-1")
    monkeypatch.setattr(
        session_manager,
        "save_session_profile_binding",
        fake_save_session_profile_binding,
    )
    monkeypatch.setattr(recording_session, "extract_arm_namespaces", lambda _snapshot: ["follower_arm"])
    monkeypatch.setattr(
        recording_session,
        "extract_recorder_topic_suffixes",
        lambda _snapshot, arm_namespaces: {
            "state_topic_suffix": "joint_states_single",
        },
    )

    recorder = _FakeRecorder()
    dataset = _FakeDataset()
    manager = RecordingSessionManager(recorder=recorder, dataset=dataset)

    try:
        asyncio.run(
            manager.create(
                session_id="session-1",
                dataset_name="dataset-a",
                task="pick-place",
                num_episodes=5,
                target_total_episodes=5,
                episode_time_s=60.0,
                reset_time_s=10.0,
            )
        )
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "action_topic_suffix unresolved" in str(exc.detail)


def test_create_raises_when_cameras_unresolved(monkeypatch):
    async def fake_resolve_profile(self, _profile):
        return SimpleNamespace(
            name="profile-a",
            source_path="/tmp/profile-a.yaml",
            snapshot={"profile": {}},
        )

    async def fake_save_session_profile_binding(**_kwargs):
        return None

    monkeypatch.setattr(RecordingSessionManager, "_resolve_profile", fake_resolve_profile)
    monkeypatch.setattr(session_manager, "get_current_user_id", lambda: "user-1")
    monkeypatch.setattr(
        session_manager,
        "save_session_profile_binding",
        fake_save_session_profile_binding,
    )
    monkeypatch.setattr(recording_session, "extract_arm_namespaces", lambda _snapshot: ["follower_arm"])
    monkeypatch.setattr(
        recording_session,
        "extract_recorder_topic_suffixes",
        lambda _snapshot, arm_namespaces: {
            "state_topic_suffix": "joint_states_single",
            "action_topic_suffix": "joint_ctrl_single",
        },
    )

    recorder = _FakeRecorder()
    recorder.build_cameras = lambda _snapshot: []
    dataset = _FakeDataset()
    manager = RecordingSessionManager(recorder=recorder, dataset=dataset)

    try:
        asyncio.run(
            manager.create(
                session_id="session-1",
                dataset_name="dataset-a",
                task="pick-place",
                num_episodes=5,
                target_total_episodes=5,
                episode_time_s=60.0,
                reset_time_s=10.0,
            )
        )
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "no enabled cameras resolved" in str(exc.detail)
