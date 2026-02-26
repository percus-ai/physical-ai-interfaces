import asyncio
import importlib.util
import os
from pathlib import Path
import sys

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")

from interfaces_backend.models.startup import StartupOperationAcceptedResponse


def _load_recording_api_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "interfaces_backend"
        / "api"
        / "recording.py"
    )
    spec = importlib.util.spec_from_file_location("interfaces_backend_api_recording_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


recording_api = _load_recording_api_module()


def test_recording_create_returns_operation_id(monkeypatch):
    accepted = StartupOperationAcceptedResponse(operation_id="op-record", message="accepted")

    class _FakeOperations:
        def create(self, *, user_id: str, kind: str):
            assert user_id == "user-1"
            assert kind == "recording_create"
            return accepted

    def _fake_create_task(coro):
        coro.close()
        return None

    monkeypatch.setattr(recording_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(recording_api, "get_startup_operations_service", lambda: _FakeOperations())
    monkeypatch.setattr(recording_api.asyncio, "create_task", _fake_create_task)

    request = recording_api.RecordingSessionCreateRequest(
        dataset_name="dataset_ok",
        task="pick and place",
        num_episodes=1,
        episode_time_s=30.0,
        reset_time_s=1.0,
    )
    response = asyncio.run(recording_api.create_session(request))
    assert response.operation_id == "op-record"
