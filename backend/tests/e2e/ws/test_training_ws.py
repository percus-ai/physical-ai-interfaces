def test_training_ws_missing_job(client):
    with client.websocket_connect("/api/training/ws/jobs/missing/logs") as ws:
        message = ws.receive_json()
        assert message["type"] == "error"

    with client.websocket_connect("/api/training/ws/jobs/missing/session") as ws:
        message = ws.receive_json()
        assert message["type"] == "error"


def test_training_ws_gpu_availability_missing_creds(client, monkeypatch):
    monkeypatch.delenv("DATACRUNCH_CLIENT_ID", raising=False)
    monkeypatch.delenv("DATACRUNCH_CLIENT_SECRET", raising=False)
    with client.websocket_connect("/api/training/ws/gpu-availability") as ws:
        message = ws.receive_json()
        assert message["type"] == "error"


def test_training_ws_verda_storage_invalid_action(client):
    with client.websocket_connect("/api/training/ws/verda/storage") as ws:
        ws.send_json({"action": "invalid", "volume_ids": []})
        message = ws.receive_json()
        assert message["type"] == "error"
