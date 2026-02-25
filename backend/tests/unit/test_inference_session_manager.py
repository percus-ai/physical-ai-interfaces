import asyncio
import os
from types import SimpleNamespace

from fastapi import HTTPException

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")

from interfaces_backend.services.inference_session import InferenceSessionManager
from interfaces_backend.services.session_manager import SessionState


class _FakeRuntime:
    def __init__(self):
        self.stop_calls: list[str | None] = []
        self.pause_calls: list[tuple[str, bool]] = []
        self.task_calls: list[tuple[str, str]] = []
        self.policy_calls: list[tuple[str, int | None]] = []

    def stop(self, session_id: str | None = None) -> bool:
        self.stop_calls.append(session_id)
        return True

    def set_paused(self, session_id: str, *, paused: bool) -> int:
        self.pause_calls.append((session_id, paused))
        return 1

    def set_task(self, *, session_id: str, task: str) -> int:
        self.task_calls.append((session_id, task))
        return 1

    def set_policy_options(self, *, session_id: str, denoising_steps: int | None = None) -> int:
        self.policy_calls.append((session_id, denoising_steps))
        return 1


class _FakeRecorder:
    def __init__(self, *, stop_exception: Exception | None = None, final_status: dict | None = None):
        self.stop_exception = stop_exception
        self.final_status = final_status
        self.stop_calls = 0
        self.wait_calls = 0

    def build_cameras(self, _profile_snapshot: dict) -> list[dict]:
        return []

    def stop(self, *, save_current: bool = True) -> dict:
        _ = save_current
        self.stop_calls += 1
        if self.stop_exception is not None:
            raise self.stop_exception
        return {"success": True, "message": "stopped"}

    def wait_until_finalized(
        self,
        dataset_id: str,
        timeout_s: float = 30.0,
        poll_interval_s: float = 0.5,
    ) -> dict | None:
        _ = (dataset_id, timeout_s, poll_interval_s)
        self.wait_calls += 1
        return self.final_status


class _FakeDataset:
    def __init__(self):
        self.marked: list[str] = []
        self.uploaded: list[str] = []

    async def mark_active(self, dataset_id: str) -> None:
        self.marked.append(dataset_id)

    async def auto_upload(self, dataset_id: str) -> None:
        self.uploaded.append(dataset_id)


class _FakeRecordingSessions:
    def __init__(self):
        self.unregistered: list[str] = []
        self.registered: list[dict] = []

    def unregister_external_session(self, session_id: str) -> None:
        self.unregistered.append(session_id)

    def register_external_session(self, **kwargs) -> None:
        self.registered.append(kwargs)


def _build_manager(
    *,
    recorder: _FakeRecorder,
    dataset: _FakeDataset,
    runtime: _FakeRuntime,
    recording_sessions: _FakeRecordingSessions,
) -> InferenceSessionManager:
    manager = InferenceSessionManager(
        runtime=runtime,
        recorder=recorder,
        dataset=dataset,
        recording_sessions=recording_sessions,
    )
    manager._sessions["session-1"] = SessionState(
        id="session-1",
        kind="inference",
        profile=SimpleNamespace(name="profile-a", snapshot={"raw": {}}),
        extras={
            "worker_session_id": "worker-1",
            "dataset_id": "dataset-1",
        },
    )
    return manager


def test_stop_treats_recorder_timeout_as_stopped_when_already_inactive() -> None:
    runtime = _FakeRuntime()
    recorder = _FakeRecorder(
        stop_exception=HTTPException(status_code=503, detail="Recorder request timed out: /api/session/stop"),
        final_status={"state": "idle", "dataset_id": ""},
    )
    dataset = _FakeDataset()
    recording_sessions = _FakeRecordingSessions()
    manager = _build_manager(
        recorder=recorder,
        dataset=dataset,
        runtime=runtime,
        recording_sessions=recording_sessions,
    )

    state = asyncio.run(manager.stop("session-1"))

    assert state.status == "stopped"
    assert runtime.stop_calls == ["worker-1"]
    assert recorder.stop_calls == 1
    assert recorder.wait_calls == 1
    assert dataset.marked == ["dataset-1"]
    assert dataset.uploaded == ["dataset-1"]
    assert recording_sessions.unregistered == ["dataset-1"]


def test_stop_keeps_dataset_unmarked_when_recorder_may_still_be_active() -> None:
    runtime = _FakeRuntime()
    recorder = _FakeRecorder(
        stop_exception=HTTPException(status_code=503, detail="Recorder request timed out: /api/session/stop"),
        final_status={"state": "recording", "dataset_id": "dataset-1"},
    )
    dataset = _FakeDataset()
    recording_sessions = _FakeRecordingSessions()
    manager = _build_manager(
        recorder=recorder,
        dataset=dataset,
        runtime=runtime,
        recording_sessions=recording_sessions,
    )

    state = asyncio.run(manager.stop("session-1"))

    assert state.status == "stopped"
    assert runtime.stop_calls == ["worker-1"]
    assert recorder.stop_calls == 1
    assert recorder.wait_calls == 1
    assert dataset.marked == []
    assert dataset.uploaded == ["dataset-1"]
    assert recording_sessions.unregistered == ["dataset-1"]


def test_resume_starts_recording_when_session_not_started() -> None:
    runtime = _FakeRuntime()
    recorder = _FakeRecorder()
    dataset = _FakeDataset()
    recording_sessions = _FakeRecordingSessions()
    manager = _build_manager(
        recorder=recorder,
        dataset=dataset,
        runtime=runtime,
        recording_sessions=recording_sessions,
    )
    manager._sessions["session-1"].status = "created"
    manager._sessions["session-1"].extras = {
        "worker_session_id": "worker-1",
        "task": "pick and place",
        "episode_time_s": 45.0,
        "reset_time_s": 8.0,
        "denoising_steps": 6,
        "recording_started": False,
    }

    class _FakeRecordingController:
        async def start(
            self,
            *,
            session,
            task,
            denoising_steps,
            episode_time_s=None,
            reset_time_s=None,
        ):
            _ = (task, denoising_steps, episode_time_s, reset_time_s)
            session.extras["dataset_id"] = "dataset-started"
            return {"success": True}

        def get_status(self, _session_id: str) -> dict:
            return {"batch_size": 20, "episode_time_s": 45.0, "reset_time_s": 8.0}

    manager._recording_controller = _FakeRecordingController()

    result = asyncio.run(manager.resume_active_recording_and_inference())

    assert result["started"] is True
    assert manager._sessions["session-1"].status == "running"
    assert manager._sessions["session-1"].extras["recording_started"] is True
    assert runtime.pause_calls == [("worker-1", False)]
    assert recording_sessions.registered[0]["session_id"] == "dataset-started"


def test_apply_active_settings_updates_pending_values_before_start() -> None:
    runtime = _FakeRuntime()
    recorder = _FakeRecorder()
    dataset = _FakeDataset()
    recording_sessions = _FakeRecordingSessions()
    manager = _build_manager(
        recorder=recorder,
        dataset=dataset,
        runtime=runtime,
        recording_sessions=recording_sessions,
    )
    manager._sessions["session-1"].extras = {
        "worker_session_id": "worker-1",
        "task": "old-task",
        "episode_time_s": 60.0,
        "reset_time_s": 10.0,
        "denoising_steps": 8,
        "recording_started": False,
    }

    result = asyncio.run(
        manager.apply_active_settings(
            task="new-task",
            episode_time_s=30.0,
            reset_time_s=5.0,
            denoising_steps=4,
        )
    )

    assert runtime.task_calls == [("worker-1", "new-task")]
    assert runtime.policy_calls == [("worker-1", 4)]
    assert manager._sessions["session-1"].extras["task"] == "new-task"
    assert manager._sessions["session-1"].extras["episode_time_s"] == 30.0
    assert manager._sessions["session-1"].extras["reset_time_s"] == 5.0
    assert manager._sessions["session-1"].extras["denoising_steps"] == 4
    assert result["task"] == "new-task"


def test_any_active_prefers_latest_session_with_worker_session_id() -> None:
    runtime = _FakeRuntime()
    recorder = _FakeRecorder()
    dataset = _FakeDataset()
    recording_sessions = _FakeRecordingSessions()
    manager = _build_manager(
        recorder=recorder,
        dataset=dataset,
        runtime=runtime,
        recording_sessions=recording_sessions,
    )
    manager._sessions["session-stale"] = SessionState(
        id="session-stale",
        kind="inference",
        status="created",
        profile=SimpleNamespace(name="profile-a", snapshot={"raw": {}}),
        extras={},
    )
    manager._sessions["session-active"] = SessionState(
        id="session-active",
        kind="inference",
        status="created",
        profile=SimpleNamespace(name="profile-a", snapshot={"raw": {}}),
        extras={"worker_session_id": "worker-2"},
    )

    active = manager.any_active()

    assert active is not None
    assert active.id == "session-active"
