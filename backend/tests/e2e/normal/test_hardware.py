def test_hardware_status(client):
    resp = client.get("/api/hardware")
    assert resp.status_code == 200
    payload = resp.json()
    assert "opencv_available" in payload
    assert "pyserial_available" in payload


def test_hardware_cameras(client):
    resp = client.get("/api/hardware/cameras", params={"max_scan": 1})
    assert resp.status_code == 200
    payload = resp.json()
    assert "cameras" in payload
    assert payload["scan_count"] == 1


def test_hardware_serial_ports(client):
    resp = client.get("/api/hardware/serial-ports")
    assert resp.status_code == 200
    payload = resp.json()
    assert "ports" in payload
