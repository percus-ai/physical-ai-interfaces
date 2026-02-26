def test_training_jobs_list_empty(client):
    resp = client.get("/api/training/jobs")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
