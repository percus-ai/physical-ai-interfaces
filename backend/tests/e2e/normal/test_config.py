def test_config(client):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    payload = resp.json()
    assert "config" in payload
    assert "data_dir" in payload["config"]

