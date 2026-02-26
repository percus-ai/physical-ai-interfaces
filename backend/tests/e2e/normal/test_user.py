def test_user_config(client):
    resp = client.get("/api/user/config")
    assert resp.status_code == 200

    update_payload = {
        "email": "tester@example.com",
        "auto_download_models": False,
    }
    resp = client.put("/api/user/config", json=update_payload)
    assert resp.status_code == 200
    assert resp.json()["email"] == "tester@example.com"


def test_user_devices(client):
    resp = client.get("/api/user/devices")
    assert resp.status_code == 200

    update_payload = {
        "cameras": {
            "top_camera": {"id": 0, "type": "opencv", "width": 640, "height": 480, "fps": 30}
        }
    }
    resp = client.put("/api/user/devices", json=update_payload)
    assert resp.status_code == 200
    assert "top_camera" in resp.json()["cameras"]


def test_user_validate_environment(client):
    resp = client.post("/api/user/validate-environment")
    assert resp.status_code == 200
    payload = resp.json()
    assert "checks" in payload
