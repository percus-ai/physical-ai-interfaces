import os
from pathlib import Path

import interfaces_backend.api.inference as inference_api


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

    monkeypatch.setattr(inference_api, "_manager", lambda: MockManager())

    response = client.get("/api/inference/runner/diagnostics")
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "running"
    assert payload["logs"]["worker_trace_path"].endswith("worker_trace.jsonl")


def test_inference_runner_start_and_stop_with_mock_manager(client, monkeypatch):
    class MockManager:
        def start(self, model_id: str, device: str | None, task: str | None) -> str:
            assert model_id == "model_a"
            assert device == "cpu"
            assert task == "pick"
            return "sess-001"

        def stop(self, session_id: str | None) -> bool:
            assert session_id == "sess-001"
            return True

    monkeypatch.setattr(inference_api, "_manager", lambda: MockManager())

    start = client.post(
        "/api/inference/runner/start",
        json={"model_id": "model_a", "device": "cpu", "task": "pick"},
    )
    assert start.status_code == 200
    assert start.json()["session_id"] == "sess-001"

    stop = client.post("/api/inference/runner/stop", json={"session_id": "sess-001"})
    assert stop.status_code == 200
    assert stop.json()["success"] is True
