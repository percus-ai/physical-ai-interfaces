def test_training_jobs_missing(client):
    resp = client.get("/api/training/jobs/missing")
    assert resp.status_code == 404

    resp = client.get("/api/training/jobs/missing/logs")
    assert resp.status_code == 404

    resp = client.get("/api/training/jobs/missing/progress")
    assert resp.status_code == 404

    resp = client.get("/api/training/jobs/missing/instance-status")
    assert resp.status_code == 404

    resp = client.post("/api/training/jobs/missing/stop")
    assert resp.status_code == 404

    resp = client.delete("/api/training/jobs/missing")
    assert resp.status_code == 404


def test_training_gpu_availability_missing_creds(client, monkeypatch):
    monkeypatch.delenv("DATACRUNCH_CLIENT_ID", raising=False)
    monkeypatch.delenv("DATACRUNCH_CLIENT_SECRET", raising=False)
    resp = client.get("/api/training/gpu-availability")
    assert resp.status_code == 503


def test_training_verda_storage_missing_creds(client, monkeypatch):
    monkeypatch.delenv("DATACRUNCH_CLIENT_ID", raising=False)
    monkeypatch.delenv("DATACRUNCH_CLIENT_SECRET", raising=False)
    resp = client.get("/api/training/verda/storage")
    assert resp.status_code == 400
