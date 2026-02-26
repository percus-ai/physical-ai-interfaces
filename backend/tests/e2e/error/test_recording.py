def test_recording_missing(client):
    resp = client.get("/api/recording/recordings/missing_project/missing_episode")
    assert resp.status_code == 404

    resp = client.delete("/api/recording/recordings/missing_project/missing_episode")
    assert resp.status_code == 404
