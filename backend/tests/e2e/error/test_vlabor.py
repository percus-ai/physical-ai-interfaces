def test_legacy_teleop_endpoints_not_found(client):
    assert client.get("/api/teleop/local/sessions").status_code == 404
    assert client.get("/api/teleop/local/status/missing").status_code == 404
    assert client.post("/api/teleop/local/missing/run").status_code == 404
    assert client.post("/api/teleop/local/stop", json={"session_id": "missing"}).status_code == 404
    assert client.post("/api/profiles/vlabor/start").status_code == 404
    assert client.post("/api/profiles/vlabor/stop").status_code == 404
