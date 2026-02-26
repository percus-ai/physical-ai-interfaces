def test_calibration_flow(client):
    resp = client.get("/api/calibration")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

    resp = client.get("/api/calibration/arms")
    assert resp.status_code == 200

    start_payload = {"arm_type": "so101_leader", "port": "dummy"}
    resp = client.post("/api/calibration/arms/start", json=start_payload)
    assert resp.status_code == 200
    session = resp.json()["session"]
    session_id = session["session_id"]
    arm_id = session["arm_id"]

    resp = client.get(f"/api/calibration/arms/{session_id}/status")
    assert resp.status_code == 200

    record_payload = {"motor_name": "shoulder_pan", "position_type": "home"}
    resp = client.post(f"/api/calibration/arms/{session_id}/record-position", json=record_payload)
    assert resp.status_code == 200

    resp = client.post(f"/api/calibration/arms/{session_id}/complete", json={"save": True})
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    resp = client.get(f"/api/calibration/arms/{arm_id}")
    assert resp.status_code == 200

    update_payload = {
        "motors": {
            "shoulder_pan": {
                "name": "shoulder_pan",
                "homing_offset": 123,
                "drive_mode": 0,
                "min_position": 10,
                "max_position": 4000,
            }
        }
    }
    resp = client.put(f"/api/calibration/arms/{arm_id}", json=update_payload)
    assert resp.status_code == 200

    resp = client.get(f"/api/calibration/export/{arm_id}")
    assert resp.status_code == 200
    assert resp.json()["arm_id"] == arm_id

    resp = client.delete(f"/api/calibration/arms/{arm_id}")
    assert resp.status_code == 200


def test_calibration_sessions(client):
    resp = client.get("/api/calibration/sessions")
    assert resp.status_code == 200
    assert "sessions" in resp.json()


def test_calibration_import(client):
    payload = {
        "calibration": {
            "arm_id": "import_arm",
            "arm_type": "so101",
            "motors": {},
        }
    }
    resp = client.post("/api/calibration/import", json=payload)
    assert resp.status_code == 200
