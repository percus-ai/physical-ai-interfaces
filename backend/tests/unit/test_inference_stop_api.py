import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")

import interfaces_backend.api.inference as inference_api
from interfaces_backend.models.inference import InferenceRunnerStopRequest


def test_stop_inference_runner_active_session_does_not_pass_duplicate_session_id(monkeypatch):
    class _FakeManager:
        def any_active(self):
            return SimpleNamespace(id="state-1")

        async def stop(self, session_id: str, **kwargs):
            assert session_id == "state-1"
            assert kwargs == {}
            return SimpleNamespace(extras={"stopped": True})

    monkeypatch.setattr(inference_api, "get_inference_session_manager", lambda: _FakeManager())

    response = asyncio.run(
        inference_api.stop_inference_runner(InferenceRunnerStopRequest(session_id="worker-1"))
    )

    assert response.success is True
    assert response.message == "inference worker stopped"
