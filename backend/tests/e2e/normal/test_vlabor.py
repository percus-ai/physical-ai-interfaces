import interfaces_backend.api.profiles as profiles_api


def test_vlabor_status_with_mocked_compose_state(client, monkeypatch):
    monkeypatch.setattr(
        profiles_api,
        "_get_vlabor_status",
        lambda: {
            "status": "running",
            "service": "vlabor",
            "state": "running",
            "status_detail": "Up 10 seconds",
        },
    )

    response = client.get("/api/profiles/vlabor/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "running"
    assert payload["service"] == "vlabor"
    assert payload["state"] == "running"
