def test_bundled_torch_ws_status(client):
    with client.websocket_connect("/api/build/ws/bundled-torch") as ws:
        ws.send_json({"action": "status"})
        message = ws.receive_json()
        assert message.get("type") == "status"
