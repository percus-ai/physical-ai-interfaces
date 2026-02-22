import os
from pathlib import Path

import interfaces_backend.api.inference as inference_api
from interfaces_backend.models.startup import StartupOperationAcceptedResponse


def test_inference_models_lists_local_models(client):
    model_dir = Path(os.environ["PHYSICAL_AI_DATA_DIR"]) / "models" / "model_local" / "pretrained_model"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "config.json").write_text('{"type":"pi05"}', encoding="utf-8")

    response = client.get("/api/inference/models")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data
    assert any(item["model_id"] == "model_local" for item in data["models"])


def test_inference_runner_status_endpoint(client):
    response = client.get("/api/inference/runner/status")
    assert response.status_code == 200
    payload = response.json()
    assert "runner_status" in payload
    assert "gpu_host_status" in payload


def test_inference_runner_diagnostics_endpoint_with_mock_manager(client, monkeypatch):
    class MockManager:
        def get_diagnostics(self):
            return {"state": "running", "logs": {"worker_trace_path": "/tmp/worker_trace.jsonl"}}

    monkeypatch.setattr(inference_api, "get_inference_runtime_manager", lambda: MockManager())

    response = client.get("/api/inference/runner/diagnostics")
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "running"
    assert payload["logs"]["worker_trace_path"].endswith("worker_trace.jsonl")


def test_inference_runner_start_returns_operation_id(client, monkeypatch):
    accepted = StartupOperationAcceptedResponse(operation_id="op-inference", message="accepted")

    class _FakeOperations:
        def create(self, *, user_id: str, kind: str):
            assert user_id == "user-1"
            assert kind == "inference_start"
            return accepted

    def _fake_create_task(coro):
        coro.close()
        return None

    monkeypatch.setattr(inference_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(inference_api, "get_startup_operations_service", lambda: _FakeOperations())
    monkeypatch.setattr(inference_api.asyncio, "create_task", _fake_create_task)

    start = client.post(
        "/api/inference/runner/start",
        json={
            "model_id": "model_a",
            "device": "cpu",
            "task": "pick",
            "policy_options": {"pi0": {"denoising_steps": 10}},
        },
    )
    assert start.status_code == 202
    assert start.json()["operation_id"] == "op-inference"
