import json
import os

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")

import interfaces_backend.api.stream as stream_api
from interfaces_backend.services.startup_operations import get_startup_operations_service


def test_startup_operation_stream_emits_payload(client, monkeypatch):
    monkeypatch.setattr(stream_api, "_require_user_id", lambda: "user-1")
    operation = get_startup_operations_service().create(
        user_id="user-1",
        kind="inference_start",
    )

    with client.stream("GET", f"/api/stream/startup/operations/{operation.operation_id}") as response:
        assert response.status_code == 200
        assert response.headers.get("content-type", "").startswith("text/event-stream")
        for line in response.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            payload = json.loads(line.removeprefix("data: "))
            assert payload["operation_id"] == operation.operation_id
            assert payload["state"] in {"queued", "running", "completed", "failed"}
            break
