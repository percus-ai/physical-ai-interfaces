def test_platform(client):
    resp = client.get("/api/platform")
    assert resp.status_code == 200
    payload = resp.json()
    assert "platform" in payload
    assert "cached" in payload

    resp = client.post("/api/platform/refresh")
    assert resp.status_code == 200
