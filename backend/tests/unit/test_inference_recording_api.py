import asyncio
import importlib.util
import os
from pathlib import Path
import sys

from fastapi import HTTPException

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")


def _load_inference_api_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "interfaces_backend"
        / "api"
        / "inference.py"
    )
    spec = importlib.util.spec_from_file_location("interfaces_backend_api_inference_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


inference_api = _load_inference_api_module()


def test_apply_inference_runner_settings_rejects_empty_request(monkeypatch) -> None:
    monkeypatch.setattr(inference_api, "require_user_id", lambda: "user-1")
    request = inference_api.InferenceRunnerSettingsApplyRequest()

    try:
        asyncio.run(inference_api.apply_inference_runner_settings(request))
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "No settings provided"


def test_apply_inference_runner_settings_returns_applied_values(monkeypatch) -> None:
    class _FakeManager:
        def any_active(self):
            return type("Active", (), {"id": "session-1"})()

        async def apply_active_settings(self, **kwargs):
            assert kwargs["task"] == "new task"
            assert kwargs["episode_time_s"] == 30.0
            assert kwargs["reset_time_s"] == 5.0
            assert kwargs["denoising_steps"] == 4
            return kwargs

    monkeypatch.setattr(inference_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(inference_api, "get_inference_session_manager", lambda: _FakeManager())

    response = asyncio.run(
        inference_api.apply_inference_runner_settings(
            inference_api.InferenceRunnerSettingsApplyRequest(
                task="new task",
                episode_time_s=30.0,
                reset_time_s=5.0,
                denoising_steps=4,
            )
        )
    )

    assert response.success is True
    assert response.task == "new task"
    assert response.episode_time_s == 30.0
    assert response.reset_time_s == 5.0
    assert response.denoising_steps == 4


def test_decide_inference_recording_continue_calls_manager(monkeypatch) -> None:
    class _FakeManager:
        def any_active(self):
            return type("Active", (), {"id": "session-1"})()

        async def decide_active_recording_continue(self, *, continue_recording: bool):
            assert continue_recording is True
            return {
                "recording_dataset_id": "dataset-1",
                "awaiting_continue_confirmation": False,
            }

    monkeypatch.setattr(inference_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(inference_api, "get_inference_session_manager", lambda: _FakeManager())

    response = asyncio.run(
        inference_api.decide_inference_recording(
            inference_api.InferenceRecordingDecisionRequest(continue_recording=True)
        )
    )

    assert response.success is True
    assert response.recording_dataset_id == "dataset-1"
    assert response.awaiting_continue_confirmation is False


def test_decide_inference_recording_stop_stops_active_session(monkeypatch) -> None:
    calls: dict[str, str] = {}

    class _FakeManager:
        def any_active(self):
            return type("Active", (), {"id": "session-1"})()

        async def stop(self, session_id: str):
            calls["stopped"] = session_id
            return None

    monkeypatch.setattr(inference_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(inference_api, "get_inference_session_manager", lambda: _FakeManager())

    response = asyncio.run(
        inference_api.decide_inference_recording(
            inference_api.InferenceRecordingDecisionRequest(continue_recording=False)
        )
    )

    assert response.success is True
    assert calls["stopped"] == "session-1"
    assert response.recording_dataset_id is None


def test_pause_inference_runner_calls_manager(monkeypatch) -> None:
    class _FakeManager:
        def any_active(self):
            return type("Active", (), {"id": "session-1"})()

        async def pause_active_recording_and_inference(self):
            return {
                "paused": True,
                "teleop_enabled": True,
                "recorder_state": "paused",
            }

    monkeypatch.setattr(inference_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(inference_api, "get_inference_session_manager", lambda: _FakeManager())

    response = asyncio.run(inference_api.pause_inference_runner())

    assert response.success is True
    assert response.paused is True
    assert response.teleop_enabled is True
    assert response.recorder_state == "paused"


def test_resume_inference_runner_calls_manager(monkeypatch) -> None:
    class _FakeManager:
        def any_active(self):
            return type("Active", (), {"id": "session-1"})()

        async def resume_active_recording_and_inference(self):
            return {
                "paused": False,
                "teleop_enabled": False,
                "recorder_state": "recording",
            }

    monkeypatch.setattr(inference_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(inference_api, "get_inference_session_manager", lambda: _FakeManager())

    response = asyncio.run(inference_api.resume_inference_runner())

    assert response.success is True
    assert response.paused is False
    assert response.teleop_enabled is False
    assert response.recorder_state == "recording"


def test_resume_inference_runner_returns_started_message_when_cold_started(monkeypatch) -> None:
    class _FakeManager:
        def any_active(self):
            return type("Active", (), {"id": "session-1"})()

        async def resume_active_recording_and_inference(self):
            return {
                "started": True,
                "paused": False,
                "teleop_enabled": False,
                "recorder_state": "warming",
            }

    monkeypatch.setattr(inference_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(inference_api, "get_inference_session_manager", lambda: _FakeManager())

    response = asyncio.run(inference_api.resume_inference_runner())

    assert response.success is True
    assert response.message == "Inference and recording started."
    assert response.recorder_state == "warming"
