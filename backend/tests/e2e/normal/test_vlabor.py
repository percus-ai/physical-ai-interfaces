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


def test_vlabor_start_and_stop_with_mocked_compose_calls(client, monkeypatch):
    state = {"status": "stopped"}

    def fake_start():
        state["status"] = "running"

    def fake_stop():
        state["status"] = "stopped"

    def fake_status():
        return {"status": state["status"], "service": "vlabor"}

    monkeypatch.setattr(profiles_api, "_start_vlabor", fake_start)
    monkeypatch.setattr(profiles_api, "_stop_vlabor", fake_stop)
    monkeypatch.setattr(profiles_api, "_get_vlabor_status", fake_status)

    start = client.post("/api/profiles/vlabor/start")
    assert start.status_code == 200
    assert start.json()["status"] == "running"

    stop = client.post("/api/profiles/vlabor/stop")
    assert stop.status_code == 200
    assert stop.json()["status"] == "stopped"
