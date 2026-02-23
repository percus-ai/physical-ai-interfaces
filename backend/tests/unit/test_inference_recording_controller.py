import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")

import interfaces_backend.services.inference_recording_controller as controller_module
from interfaces_backend.services.inference_recording_controller import InferenceRecordingController
from interfaces_backend.services.session_manager import SessionState


class _FakeRecorder:
    def __init__(self) -> None:
        self.started_payloads: list[dict] = []
        self.updated_payloads: list[dict] = []
        self.pause_calls = 0
        self.resume_calls = 0
        self._status: dict = {"state": "idle", "dataset_id": ""}

    def build_cameras(self, _profile_snapshot: dict) -> list[dict]:
        return [{"name": "front", "topic": "/cam/front/compressed"}]

    def start(self, payload: dict) -> dict:
        self.started_payloads.append(payload)
        self._status = {
            "state": "recording",
            "dataset_id": payload["dataset_id"],
            "episode_count": 0,
            "num_episodes": payload["num_episodes"],
        }
        return {"success": True, "message": "started", "dataset_id": payload["dataset_id"]}

    def status(self) -> dict:
        return dict(self._status)

    def update(self, payload: dict) -> dict:
        self.updated_payloads.append(payload)
        return {"success": True, "message": "updated"}

    def pause(self) -> dict:
        self.pause_calls += 1
        if self._status.get("dataset_id"):
            self._status["state"] = "paused"
        return {"success": True, "message": "paused", "dataset_id": self._status.get("dataset_id")}

    def resume(self) -> dict:
        self.resume_calls += 1
        if self._status.get("dataset_id"):
            self._status["state"] = "recording"
        return {"success": True, "message": "resumed", "dataset_id": self._status.get("dataset_id")}


class _FakeDataset:
    def __init__(self) -> None:
        self.upsert_calls: list[dict] = []

    async def upsert_record(self, **kwargs) -> None:
        self.upsert_calls.append(kwargs)


class _FakeRuntime:
    def __init__(self) -> None:
        self.task_calls: list[tuple[str, str]] = []
        self.policy_calls: list[tuple[str, int | None]] = []
        self.pause_calls: list[tuple[str, bool]] = []

    def set_task(self, *, session_id: str, task: str) -> int:
        self.task_calls.append((session_id, task))
        return 1

    def set_policy_options(self, *, session_id: str, denoising_steps: int | None = None) -> int:
        self.policy_calls.append((session_id, denoising_steps))
        return 1

    def set_paused(self, session_id: str, *, paused: bool) -> int:
        self.pause_calls.append((session_id, paused))
        return 1


class _FakeDashboard:
    def __init__(self) -> None:
        self.teleop_calls: list[bool] = []

    async def set_teleop_enabled(self, *, enabled: bool, timeout_s: float = 3.0):
        _ = timeout_s
        self.teleop_calls.append(bool(enabled))
        return {"success": True, "enabled": bool(enabled)}


def _build_profile_snapshot() -> dict:
    return {
        "profile": {
            "lerobot": {
                "left_arm": {
                    "namespace": "left_arm",
                    "topic": "/left_arm/joint_states",
                    "action_topic": "/left_arm/joint_actions",
                },
                "right_arm": {
                    "namespace": "right_arm",
                    "topic": "/right_arm/joint_states",
                    "action_topic": "/right_arm/joint_actions",
                },
            }
        }
    }


def _build_session(session_id: str = "inf-1") -> SessionState:
    return SessionState(
        id=session_id,
        kind="inference",
        profile=SimpleNamespace(name="profile-a", snapshot=_build_profile_snapshot()),
        extras={"worker_session_id": "worker-1"},
    )


def test_start_registers_inference_recording_state(monkeypatch) -> None:
    recorder = _FakeRecorder()
    dataset = _FakeDataset()
    runtime = _FakeRuntime()
    dashboard = _FakeDashboard()
    controller = InferenceRecordingController(
        recorder=recorder, dataset=dataset, runtime=runtime, dashboard=dashboard
    )
    session = _build_session()

    async def _fake_save_session_profile_binding(**_kwargs) -> None:
        return None

    monkeypatch.setattr(controller_module, "generate_dataset_id", lambda: "dataset-fixed")
    monkeypatch.setattr(
        controller_module,
        "save_session_profile_binding",
        _fake_save_session_profile_binding,
    )
    monkeypatch.setattr(controller, "_start_monitor_loop", lambda _session_id: None)

    result = asyncio.run(
        controller.start(
            session=session,
            task="pick and place",
            denoising_steps=8,
        )
    )

    assert result is not None
    assert session.extras["dataset_id"] == "dataset-fixed"
    assert recorder.started_payloads[0]["dataset_id"] == "dataset-fixed"
    assert recorder.started_payloads[0]["num_episodes"] == 20
    assert dataset.upsert_calls[0]["target_total_episodes"] == 20
    assert dashboard.teleop_calls == [False]
    status = controller.get_status("inf-1")
    assert status["recording_dataset_id"] == "dataset-fixed"
    assert status["recording_active"] is True
    assert status["awaiting_continue_confirmation"] is False


def test_get_status_marks_awaiting_continue_when_completed(monkeypatch) -> None:
    recorder = _FakeRecorder()
    dataset = _FakeDataset()
    runtime = _FakeRuntime()
    dashboard = _FakeDashboard()
    controller = InferenceRecordingController(
        recorder=recorder, dataset=dataset, runtime=runtime, dashboard=dashboard
    )
    session = _build_session()

    async def _fake_save_session_profile_binding(**_kwargs) -> None:
        return None

    monkeypatch.setattr(controller_module, "generate_dataset_id", lambda: "dataset-fixed")
    monkeypatch.setattr(
        controller_module,
        "save_session_profile_binding",
        _fake_save_session_profile_binding,
    )
    monkeypatch.setattr(controller, "_start_monitor_loop", lambda _session_id: None)

    asyncio.run(
        controller.start(
            session=session,
            task="pick and place",
            denoising_steps=8,
        )
    )
    recorder._status = {
        "state": "completed",
        "dataset_id": "dataset-fixed",
        "episode_count": 20,
        "num_episodes": 20,
    }

    status = controller.get_status("inf-1")
    assert status["recording_active"] is False
    assert status["awaiting_continue_confirmation"] is True
    assert status["episode_count"] == 20
    assert status["num_episodes"] == 20


def test_decide_continue_starts_next_batch_on_same_dataset(monkeypatch) -> None:
    recorder = _FakeRecorder()
    dataset = _FakeDataset()
    runtime = _FakeRuntime()
    dashboard = _FakeDashboard()
    controller = InferenceRecordingController(
        recorder=recorder, dataset=dataset, runtime=runtime, dashboard=dashboard
    )
    session = _build_session()

    async def _fake_save_session_profile_binding(**_kwargs) -> None:
        return None

    monkeypatch.setattr(controller_module, "generate_dataset_id", lambda: "dataset-fixed")
    monkeypatch.setattr(
        controller_module,
        "save_session_profile_binding",
        _fake_save_session_profile_binding,
    )
    monkeypatch.setattr(controller, "_start_monitor_loop", lambda _session_id: None)

    asyncio.run(
        controller.start(
            session=session,
            task="pick and place",
            denoising_steps=8,
        )
    )
    recorder._status = {
        "state": "completed",
        "dataset_id": "dataset-fixed",
        "episode_count": 20,
        "num_episodes": 20,
    }

    result = asyncio.run(
        controller.decide_continue(
            inference_session_id="inf-1",
            continue_recording=True,
        )
    )

    assert result["recording_dataset_id"] == "dataset-fixed"
    assert result["awaiting_continue_confirmation"] is False
    assert len(recorder.started_payloads) == 2
    assert recorder.started_payloads[1]["dataset_id"] == "dataset-fixed"
    assert recorder.started_payloads[1]["num_episodes"] == 20
    assert dataset.upsert_calls[-1]["target_total_episodes"] == 40


def test_apply_settings_updates_runtime_and_recorder(monkeypatch) -> None:
    recorder = _FakeRecorder()
    dataset = _FakeDataset()
    runtime = _FakeRuntime()
    dashboard = _FakeDashboard()
    controller = InferenceRecordingController(
        recorder=recorder, dataset=dataset, runtime=runtime, dashboard=dashboard
    )
    session = _build_session()

    async def _fake_save_session_profile_binding(**_kwargs) -> None:
        return None

    monkeypatch.setattr(controller_module, "generate_dataset_id", lambda: "dataset-fixed")
    monkeypatch.setattr(
        controller_module,
        "save_session_profile_binding",
        _fake_save_session_profile_binding,
    )
    monkeypatch.setattr(controller, "_start_monitor_loop", lambda _session_id: None)

    asyncio.run(
        controller.start(
            session=session,
            task="pick and place",
            denoising_steps=8,
        )
    )
    recorder._status = {
        "state": "recording",
        "dataset_id": "dataset-fixed",
        "episode_count": 3,
        "num_episodes": 20,
    }

    applied = asyncio.run(
        controller.apply_settings(
            inference_session_id="inf-1",
            worker_session_id="worker-1",
            task="new task",
            episode_time_s=30.0,
            reset_time_s=5.0,
            denoising_steps=4,
        )
    )

    assert runtime.task_calls == [("worker-1", "new task")]
    assert runtime.policy_calls == [("worker-1", 4)]
    assert recorder.updated_payloads[-1] == {
        "task": "new task",
        "episode_time_s": 30.0,
        "reset_time_s": 5.0,
    }
    assert dataset.upsert_calls[-1]["episode_time_s"] == 30.0
    assert dataset.upsert_calls[-1]["reset_time_s"] == 5.0
    assert applied["task"] == "new task"
    assert applied["denoising_steps"] == 4


def test_manual_pause_is_cleared_when_recorder_progresses_after_redo(monkeypatch) -> None:
    recorder = _FakeRecorder()
    dataset = _FakeDataset()
    runtime = _FakeRuntime()
    dashboard = _FakeDashboard()
    controller = InferenceRecordingController(
        recorder=recorder, dataset=dataset, runtime=runtime, dashboard=dashboard
    )
    session = _build_session()

    async def _fake_save_session_profile_binding(**_kwargs) -> None:
        return None

    monkeypatch.setattr(controller_module, "generate_dataset_id", lambda: "dataset-fixed")
    monkeypatch.setattr(
        controller_module,
        "save_session_profile_binding",
        _fake_save_session_profile_binding,
    )
    monkeypatch.setattr(controller, "_start_monitor_loop", lambda _session_id: None)

    asyncio.run(
        controller.start(
            session=session,
            task="pick and place",
            denoising_steps=8,
        )
    )

    paused = asyncio.run(
        controller.set_manual_pause(
            inference_session_id="inf-1",
            paused=True,
        )
    )
    assert paused["paused"] is True
    assert paused["teleop_enabled"] is False
    assert recorder.pause_calls == 1
    assert runtime.pause_calls[-1] == ("worker-1", True)
    assert dashboard.teleop_calls == [False]

    state = controller._get_state_or_raise("inf-1")
    recorder._status = {"state": "resetting", "dataset_id": "dataset-fixed"}
    asyncio.run(controller._sync_mode_from_status(state, recorder.status()))
    assert state.manual_paused is False
    assert state.inference_paused is True
    assert state.teleop_enabled is True
    assert dashboard.teleop_calls[-1] is True

    recorder._status = {"state": "recording", "dataset_id": "dataset-fixed"}
    asyncio.run(controller._sync_mode_from_status(state, recorder.status()))
    assert state.inference_paused is False
    assert state.teleop_enabled is False
    assert dashboard.teleop_calls[-1] is False
    assert runtime.pause_calls[-1] == ("worker-1", False)


def test_finalizing_phase_uses_same_transition_as_reset(monkeypatch) -> None:
    recorder = _FakeRecorder()
    dataset = _FakeDataset()
    runtime = _FakeRuntime()
    dashboard = _FakeDashboard()
    controller = InferenceRecordingController(
        recorder=recorder, dataset=dataset, runtime=runtime, dashboard=dashboard
    )
    session = _build_session()

    async def _fake_save_session_profile_binding(**_kwargs) -> None:
        return None

    monkeypatch.setattr(controller_module, "generate_dataset_id", lambda: "dataset-fixed")
    monkeypatch.setattr(
        controller_module,
        "save_session_profile_binding",
        _fake_save_session_profile_binding,
    )
    monkeypatch.setattr(controller, "_start_monitor_loop", lambda _session_id: None)

    asyncio.run(
        controller.start(
            session=session,
            task="pick and place",
            denoising_steps=8,
        )
    )
    state = controller._get_state_or_raise("inf-1")

    finalizing_status = {
        "state": "recording",
        "phase": "finalizing",
        "is_finalizing_episode": True,
        "dataset_id": "dataset-fixed",
    }
    asyncio.run(controller._sync_mode_from_status(state, finalizing_status))
    assert state.inference_paused is True
    assert state.teleop_enabled is True
    assert runtime.pause_calls[-1] == ("worker-1", True)
    assert dashboard.teleop_calls[-1] is True

    recorder._status = {"state": "recording", "phase": "recording", "dataset_id": "dataset-fixed"}
    asyncio.run(controller._sync_mode_from_status(state, recorder.status()))
    assert state.inference_paused is False
    assert state.teleop_enabled is False
    assert runtime.pause_calls[-1] == ("worker-1", False)
    assert dashboard.teleop_calls[-1] is False
