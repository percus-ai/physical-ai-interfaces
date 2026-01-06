"""Calibration API router."""

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from interfaces_backend.models.calibration import (
    MotorCalibrationModel,
    CalibrationDataModel,
    CalibrationListResponse,
    CalibrationStartRequest,
    CalibrationSession,
    CalibrationStartResponse,
    RecordPositionRequest,
    RecordPositionResponse,
    CalibrationCompleteRequest,
    CalibrationCompleteResponse,
    CalibrationUpdateRequest,
    CalibrationImportRequest,
    CalibrationExportResponse,
    CalibrationSessionsResponse,
)

router = APIRouter(prefix="/api/calibration", tags=["calibration"])

# In-memory session storage
_sessions: Dict[str, dict] = {}

# Default calibration root
CALIBRATION_ROOT = Path.home() / ".cache" / "percus_ai" / "calibration"

# Standard motor names for SO-101
SO101_MOTORS = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
]

# Motor ID mapping for SO-101
SO101_MOTOR_IDS = {
    "shoulder_pan": 1,
    "shoulder_lift": 2,
    "elbow_flex": 3,
    "wrist_flex": 4,
    "wrist_roll": 5,
    "gripper": 6,
}

# Active motor buses for WebSocket sessions
_motor_buses: Dict[str, Any] = {}


def _get_motor_bus(port: str, arm_type: str = "so101"):
    """Get or create a motor bus for the given port."""
    if port in _motor_buses:
        return _motor_buses[port]

    try:
        from lerobot.common.robot_devices.motors.feetech import FeetechMotorsBus

        # Determine motor IDs based on arm type
        arm_base = arm_type.split("_")[0]
        if arm_base in ("so101", "so100"):
            motor_ids = SO101_MOTOR_IDS
        else:
            motor_ids = SO101_MOTOR_IDS

        # Create motor configuration
        motors = {name: (motor_id, "sts3215") for name, motor_id in motor_ids.items()}

        bus = FeetechMotorsBus(port=port, motors=motors)
        bus.connect()
        _motor_buses[port] = bus
        return bus
    except Exception:
        return None


def _close_motor_bus(port: str) -> None:
    """Close and remove a motor bus."""
    if port in _motor_buses:
        try:
            _motor_buses[port].disconnect()
        except Exception:
            pass
        del _motor_buses[port]


def _read_motor_positions_batch(bus, motors: list[str]) -> Dict[str, Optional[int]]:
    """Read current positions from motors using batch sync_read.

    Returns dict with motor positions. Failed motors have None value.
    Always uses sync_read - partial failures cannot be detected reliably
    (LeRobot's sync_read doesn't check isAvailable, returns 0 for failed reads).

    Note: Complete failure (ConnectionError) results in all None.
          Partial failures are indistinguishable from valid 0 positions.
    """
    positions: Dict[str, Optional[int]] = {}
    valid_motors = [m for m in motors if m in SO101_MOTOR_IDS]

    if not valid_motors:
        return positions

    # Initialize all motors as None (failed until proven otherwise)
    for motor_name in valid_motors:
        positions[motor_name] = None

    try:
        # sync_read returns dict {motor_name: value}
        # On partial failure, non-responding motors get 0 (not distinguishable from valid 0)
        result = bus.sync_read("Present_Position", valid_motors, normalize=False)

        if isinstance(result, dict):
            for motor_name in valid_motors:
                val = result.get(motor_name)
                if val is not None:
                    positions[motor_name] = int(val) if not hasattr(val, "__len__") else int(val[0])
    except ConnectionError:
        # Complete communication failure - all motors marked as None (already initialized)
        pass
    except Exception:
        # Other errors - also mark all as failed
        pass

    return positions


def _read_motor_positions(bus, motors: list[str]) -> Dict[str, int]:
    """Read motor positions with fallback to placeholder for failed reads."""
    batch_result = _read_motor_positions_batch(bus, motors)
    # Replace None with placeholder
    return {m: (v if v is not None else 2048) for m, v in batch_result.items()}


def _list_all_calibrations() -> list[dict]:
    """List all calibrations across all arm types."""
    calibrations = []

    if not CALIBRATION_ROOT.exists():
        return calibrations

    for arm_type_dir in CALIBRATION_ROOT.iterdir():
        if not arm_type_dir.is_dir():
            continue

        arm_type = arm_type_dir.name

        for calib_file in arm_type_dir.glob("*.json"):
            try:
                import json
                with open(calib_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                motors = {}
                for motor_name, motor_data in data.get("motors", {}).items():
                    motors[motor_name] = MotorCalibrationModel(
                        name=motor_name,
                        homing_offset=motor_data.get("homing_offset", 0),
                        drive_mode=motor_data.get("drive_mode", 0),
                        min_position=motor_data.get("min_position", 0),
                        max_position=motor_data.get("max_position", 4095),
                    )

                calibrations.append({
                    "arm_id": data.get("arm_id", calib_file.stem),
                    "arm_type": arm_type,
                    "motors": motors,
                    "created_at": data.get("created_at"),
                })
            except Exception:
                continue

    return calibrations


def _load_calibration_file(arm_id: str, arm_type: str) -> Optional[dict]:
    """Load calibration from file."""
    calib_file = CALIBRATION_ROOT / arm_type / f"{arm_id}.json"

    if not calib_file.exists():
        return None

    try:
        import json
        with open(calib_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_calibration_file(arm_id: str, arm_type: str, data: dict) -> Path:
    """Save calibration to file."""
    import json

    calib_dir = CALIBRATION_ROOT / arm_type
    calib_dir.mkdir(parents=True, exist_ok=True)

    calib_file = calib_dir / f"{arm_id}.json"
    with open(calib_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return calib_file


@router.get("", response_model=CalibrationListResponse)
async def list_calibrations():
    """List all arm calibrations."""
    calibrations_data = _list_all_calibrations()

    calibrations = [
        CalibrationDataModel(
            arm_id=c["arm_id"],
            arm_type=c["arm_type"],
            motors=c["motors"],
            created_at=c.get("created_at"),
        )
        for c in calibrations_data
    ]

    return CalibrationListResponse(calibrations=calibrations, total=len(calibrations))


@router.get("/arms", response_model=CalibrationListResponse)
async def list_calibrations_by_arm_type(arm_type: Optional[str] = None):
    """List calibrations filtered by arm type."""
    calibrations_data = _list_all_calibrations()

    if arm_type:
        calibrations_data = [c for c in calibrations_data if c["arm_type"] == arm_type]

    calibrations = [
        CalibrationDataModel(
            arm_id=c["arm_id"],
            arm_type=c["arm_type"],
            motors=c["motors"],
            created_at=c.get("created_at"),
        )
        for c in calibrations_data
    ]

    return CalibrationListResponse(calibrations=calibrations, total=len(calibrations))


@router.post("/arms/start", response_model=CalibrationStartResponse)
async def start_calibration(request: CalibrationStartRequest):
    """Start a calibration session.

    Creates a calibration session for an arm. The session allows
    recording motor positions interactively.
    """
    session_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    # Generate arm_id if not provided
    arm_id = request.arm_id or f"arm_{session_id}"

    # Determine motors based on arm type
    arm_base_type = request.arm_type.split("_")[0]
    if arm_base_type == "so101" or arm_base_type == "so100":
        motors_to_calibrate = SO101_MOTORS.copy()
    else:
        motors_to_calibrate = SO101_MOTORS.copy()

    session_data = {
        "session_id": session_id,
        "arm_id": arm_id,
        "arm_type": request.arm_type,
        "port": request.port,
        "status": "pending",
        "started_at": now,
        "motors_to_calibrate": motors_to_calibrate,
        "calibrated_motors": [],
        "current_motor": None,
        "motor_data": {},
        "bus": None,
    }
    _sessions[session_id] = session_data

    return CalibrationStartResponse(
        session=CalibrationSession(
            session_id=session_id,
            arm_id=arm_id,
            arm_type=request.arm_type,
            port=request.port,
            status="pending",
            started_at=now,
            motors_to_calibrate=motors_to_calibrate,
            calibrated_motors=[],
            current_motor=None,
        ),
        message="Calibration session created. Record positions for each motor.",
    )


@router.get("/arms/{session_id}/status", response_model=CalibrationSession)
async def get_calibration_session(session_id: str):
    """Get calibration session status."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    s = _sessions[session_id]
    return CalibrationSession(
        session_id=s["session_id"],
        arm_id=s["arm_id"],
        arm_type=s["arm_type"],
        port=s["port"],
        status=s["status"],
        started_at=s["started_at"],
        motors_to_calibrate=s["motors_to_calibrate"],
        calibrated_motors=s["calibrated_motors"],
        current_motor=s.get("current_motor"),
    )


@router.post("/arms/{session_id}/record-position", response_model=RecordPositionResponse)
async def record_motor_position(session_id: str, request: RecordPositionRequest):
    """Record a motor position during calibration.

    Position types:
    - min: Minimum position limit
    - max: Maximum position limit
    - home: Home/zero position
    """
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    session = _sessions[session_id]

    if request.motor_name not in session["motors_to_calibrate"]:
        raise HTTPException(
            status_code=400,
            detail=f"Motor not in calibration list: {request.motor_name}",
        )

    if request.position_type not in ("min", "max", "home"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid position type: {request.position_type}. Use min, max, or home.",
        )

    session["status"] = "in_progress"
    session["current_motor"] = request.motor_name

    # Initialize motor data if needed
    if request.motor_name not in session["motor_data"]:
        session["motor_data"][request.motor_name] = {
            "name": request.motor_name,
            "homing_offset": 0,
            "drive_mode": 0,
            "min_position": 0,
            "max_position": 4095,
        }

    # Read actual position from motor via LeRobot
    position = 2048  # Default placeholder
    port = session.get("port")
    if port:
        bus = session.get("bus") or _get_motor_bus(port, session["arm_type"])
        if bus:
            session["bus"] = bus
            positions = _read_motor_positions(bus, [request.motor_name])
            position = positions.get(request.motor_name, 2048)

    # Record position based on type
    motor_data = session["motor_data"][request.motor_name]
    if request.position_type == "min":
        motor_data["min_position"] = position
    elif request.position_type == "max":
        motor_data["max_position"] = position
    elif request.position_type == "home":
        motor_data["homing_offset"] = position

    # Mark motor as calibrated if all positions recorded
    if request.motor_name not in session["calibrated_motors"]:
        # Check if we have min and max
        if motor_data.get("min_position", 0) != motor_data.get("max_position", 4095):
            session["calibrated_motors"].append(request.motor_name)

    return RecordPositionResponse(
        motor_name=request.motor_name,
        position_type=request.position_type,
        position=position,
        success=True,
        message=f"Recorded {request.position_type} position for {request.motor_name}",
    )


@router.post("/arms/{session_id}/complete", response_model=CalibrationCompleteResponse)
async def complete_calibration(session_id: str, request: CalibrationCompleteRequest):
    """Complete calibration session and optionally save."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    session = _sessions[session_id]

    # Build calibration data
    arm_base_type = session["arm_type"].split("_")[0]
    motors = {}
    for motor_name, motor_data in session.get("motor_data", {}).items():
        motors[motor_name] = MotorCalibrationModel(
            name=motor_name,
            homing_offset=motor_data.get("homing_offset", 0),
            drive_mode=motor_data.get("drive_mode", 0),
            min_position=motor_data.get("min_position", 0),
            max_position=motor_data.get("max_position", 4095),
        )

    calibration = CalibrationDataModel(
        arm_id=session["arm_id"],
        arm_type=arm_base_type,
        motors=motors,
        created_at=datetime.now().isoformat(),
    )

    # Save if requested
    if request.save:
        try:
            save_data = {
                "arm_id": calibration.arm_id,
                "arm_type": calibration.arm_type,
                "motors": {
                    name: {
                        "name": m.name,
                        "homing_offset": m.homing_offset,
                        "drive_mode": m.drive_mode,
                        "min_position": m.min_position,
                        "max_position": m.max_position,
                    }
                    for name, m in calibration.motors.items()
                },
                "created_at": calibration.created_at,
            }
            _save_calibration_file(calibration.arm_id, calibration.arm_type, save_data)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save calibration: {e}")

    session["status"] = "completed"
    del _sessions[session_id]

    return CalibrationCompleteResponse(
        session_id=session_id,
        arm_id=calibration.arm_id,
        success=True,
        message="Calibration completed and saved" if request.save else "Calibration completed",
        calibration=calibration,
    )


@router.get("/arms/{arm_id}", response_model=CalibrationDataModel)
async def get_calibration(arm_id: str, arm_type: str = "so101"):
    """Get calibration data for an arm."""
    data = _load_calibration_file(arm_id, arm_type)

    if not data:
        raise HTTPException(status_code=404, detail=f"Calibration not found: {arm_id}")

    motors = {}
    for motor_name, motor_data in data.get("motors", {}).items():
        motors[motor_name] = MotorCalibrationModel(
            name=motor_name,
            homing_offset=motor_data.get("homing_offset", 0),
            drive_mode=motor_data.get("drive_mode", 0),
            min_position=motor_data.get("min_position", 0),
            max_position=motor_data.get("max_position", 4095),
        )

    return CalibrationDataModel(
        arm_id=data.get("arm_id", arm_id),
        arm_type=arm_type,
        motors=motors,
        created_at=data.get("created_at"),
    )


@router.put("/arms/{arm_id}", response_model=CalibrationDataModel)
async def update_calibration(arm_id: str, request: CalibrationUpdateRequest, arm_type: str = "so101"):
    """Update calibration data for an arm."""
    data = _load_calibration_file(arm_id, arm_type)

    if not data:
        raise HTTPException(status_code=404, detail=f"Calibration not found: {arm_id}")

    # Update motors
    for motor_name, motor in request.motors.items():
        data["motors"][motor_name] = {
            "name": motor.name,
            "homing_offset": motor.homing_offset,
            "drive_mode": motor.drive_mode,
            "min_position": motor.min_position,
            "max_position": motor.max_position,
        }

    # Save updated calibration
    _save_calibration_file(arm_id, arm_type, data)

    motors = {}
    for motor_name, motor_data in data.get("motors", {}).items():
        motors[motor_name] = MotorCalibrationModel(
            name=motor_name,
            homing_offset=motor_data.get("homing_offset", 0),
            drive_mode=motor_data.get("drive_mode", 0),
            min_position=motor_data.get("min_position", 0),
            max_position=motor_data.get("max_position", 4095),
        )

    return CalibrationDataModel(
        arm_id=data.get("arm_id", arm_id),
        arm_type=arm_type,
        motors=motors,
        created_at=data.get("created_at"),
    )


@router.delete("/arms/{arm_id}")
async def delete_calibration(arm_id: str, arm_type: str = "so101"):
    """Delete calibration for an arm."""
    calib_file = CALIBRATION_ROOT / arm_type / f"{arm_id}.json"

    if not calib_file.exists():
        raise HTTPException(status_code=404, detail=f"Calibration not found: {arm_id}")

    try:
        calib_file.unlink()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete calibration: {e}")

    return {"arm_id": arm_id, "message": "Calibration deleted"}


@router.post("/import", response_model=CalibrationDataModel)
async def import_calibration(request: CalibrationImportRequest):
    """Import calibration from data."""
    calibration = request.calibration

    save_data = {
        "arm_id": calibration.arm_id,
        "arm_type": calibration.arm_type,
        "motors": {
            name: {
                "name": m.name,
                "homing_offset": m.homing_offset,
                "drive_mode": m.drive_mode,
                "min_position": m.min_position,
                "max_position": m.max_position,
            }
            for name, m in calibration.motors.items()
        },
        "created_at": calibration.created_at or datetime.now().isoformat(),
    }

    try:
        _save_calibration_file(calibration.arm_id, calibration.arm_type, save_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to import calibration: {e}")

    return calibration


@router.get("/export/{arm_id}", response_model=CalibrationExportResponse)
async def export_calibration(arm_id: str, arm_type: str = "so101"):
    """Export calibration as JSON."""
    data = _load_calibration_file(arm_id, arm_type)

    if not data:
        raise HTTPException(status_code=404, detail=f"Calibration not found: {arm_id}")

    motors = {}
    for motor_name, motor_data in data.get("motors", {}).items():
        motors[motor_name] = MotorCalibrationModel(
            name=motor_name,
            homing_offset=motor_data.get("homing_offset", 0),
            drive_mode=motor_data.get("drive_mode", 0),
            min_position=motor_data.get("min_position", 0),
            max_position=motor_data.get("max_position", 4095),
        )

    calibration = CalibrationDataModel(
        arm_id=data.get("arm_id", arm_id),
        arm_type=arm_type,
        motors=motors,
        created_at=data.get("created_at"),
    )

    export_path = str(CALIBRATION_ROOT / arm_type / f"{arm_id}.json")

    return CalibrationExportResponse(
        arm_id=arm_id,
        arm_type=arm_type,
        calibration=calibration,
        export_path=export_path,
    )


@router.get("/sessions", response_model=CalibrationSessionsResponse)
async def list_calibration_sessions():
    """List active calibration sessions."""
    sessions = [
        CalibrationSession(
            session_id=s["session_id"],
            arm_id=s["arm_id"],
            arm_type=s["arm_type"],
            port=s["port"],
            status=s["status"],
            started_at=s["started_at"],
            motors_to_calibrate=s["motors_to_calibrate"],
            calibrated_motors=s["calibrated_motors"],
            current_motor=s.get("current_motor"),
        )
        for s in _sessions.values()
    ]

    return CalibrationSessionsResponse(sessions=sessions, total=len(sessions))


# WebSocket for real-time motor position streaming
@router.websocket("/arms/{session_id}/stream")
async def motor_position_stream(websocket: WebSocket, session_id: str):
    """Stream motor positions in real-time via WebSocket.

    Client can send JSON commands:
    - {"command": "set_rate", "rate_hz": 30} - Change streaming rate (1-100Hz)
    - {"command": "record", "motor": "shoulder_pan", "type": "min"} - Record position
    - {"command": "stop"} - Stop streaming and close

    Server sends:
    - {"type": "positions", "data": {"shoulder_pan": 2048, ...}, "errors": ["gripper"]}
    - {"type": "recorded", "motor": "...", "position_type": "min", "position": 2048}
    - {"type": "error", "message": "..."}
    """
    await websocket.accept()

    if session_id not in _sessions:
        await websocket.send_json({"type": "error", "message": f"Session not found: {session_id}"})
        await websocket.close()
        return

    session = _sessions[session_id]
    port = session.get("port")

    if not port:
        await websocket.send_json({"type": "error", "message": "No port configured for session"})
        await websocket.close()
        return

    # Get or create motor bus
    bus = session.get("bus") or _get_motor_bus(port, session["arm_type"])
    if not bus:
        await websocket.send_json({
            "type": "error",
            "message": "Failed to connect to motor bus. Check port and LeRobot installation."
        })
        await websocket.close()
        return

    session["bus"] = bus
    session["status"] = "streaming"

    # Streaming configuration
    rate_hz = 15  # Default rate
    min_rate = 1
    max_rate = 100
    running = True

    async def stream_positions():
        """Background task to stream motor positions."""
        nonlocal running, rate_hz
        motors = session["motors_to_calibrate"]

        while running:
            try:
                # Read positions with error tracking
                batch_result = _read_motor_positions_batch(bus, motors)

                # Separate successful reads from errors
                positions = {}
                errors = []
                for motor_name, pos in batch_result.items():
                    if pos is not None:
                        positions[motor_name] = pos
                    else:
                        errors.append(motor_name)

                await websocket.send_json({
                    "type": "positions",
                    "data": positions,
                    "errors": errors,
                    "rate_hz": rate_hz,
                })

                # Sleep for rate interval
                await asyncio.sleep(1.0 / rate_hz)

            except WebSocketDisconnect:
                running = False
                break
            except Exception as e:
                try:
                    await websocket.send_json({"type": "error", "message": str(e)})
                except Exception:
                    running = False
                    break

    # Start streaming task
    stream_task = asyncio.create_task(stream_positions())

    try:
        # Handle incoming commands
        while running:
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)

                command = message.get("command")

                if command == "set_rate":
                    new_rate = message.get("rate_hz", rate_hz)
                    rate_hz = max(min_rate, min(max_rate, int(new_rate)))
                    await websocket.send_json({
                        "type": "rate_changed",
                        "rate_hz": rate_hz,
                    })

                elif command == "record":
                    motor_name = message.get("motor")
                    position_type = message.get("type")

                    if motor_name not in session["motors_to_calibrate"]:
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Unknown motor: {motor_name}",
                        })
                        continue

                    if position_type not in ("min", "max", "home"):
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Invalid position type: {position_type}",
                        })
                        continue

                    # Read current position for this motor
                    positions = _read_motor_positions(bus, [motor_name])
                    position = positions.get(motor_name, 2048)

                    # Initialize motor data if needed
                    if motor_name not in session["motor_data"]:
                        session["motor_data"][motor_name] = {
                            "name": motor_name,
                            "homing_offset": 0,
                            "drive_mode": 0,
                            "min_position": 0,
                            "max_position": 4095,
                        }

                    # Record position
                    motor_data = session["motor_data"][motor_name]
                    if position_type == "min":
                        motor_data["min_position"] = position
                    elif position_type == "max":
                        motor_data["max_position"] = position
                    elif position_type == "home":
                        motor_data["homing_offset"] = position

                    # Update calibrated motors list
                    if motor_name not in session["calibrated_motors"]:
                        if motor_data.get("min_position", 0) != motor_data.get("max_position", 4095):
                            session["calibrated_motors"].append(motor_name)

                    await websocket.send_json({
                        "type": "recorded",
                        "motor": motor_name,
                        "position_type": position_type,
                        "position": position,
                    })

                elif command == "stop":
                    running = False
                    break

            except asyncio.TimeoutError:
                # No message received, continue streaming
                continue
            except WebSocketDisconnect:
                running = False
                break

    except WebSocketDisconnect:
        pass
    finally:
        running = False
        stream_task.cancel()
        try:
            await stream_task
        except asyncio.CancelledError:
            pass

        # Update session status
        if session_id in _sessions:
            _sessions[session_id]["status"] = "pending"
