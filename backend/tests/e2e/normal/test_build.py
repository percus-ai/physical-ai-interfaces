def test_bundled_torch_status(client):
    resp = client.get("/api/build/bundled-torch/status")
    assert resp.status_code == 200
    payload = resp.json()
    assert "exists" in payload
    assert "is_valid" in payload
