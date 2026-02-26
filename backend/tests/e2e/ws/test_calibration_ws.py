def test_calibration_stream_session_missing(client):
    with client.websocket_connect("/api/calibration/arms/missing/stream") as ws:
        message = ws.receive_json()
        assert message["type"] == "error"
