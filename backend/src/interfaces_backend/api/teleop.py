"""Teleoperation API router."""

import uuid
import asyncio
import threading
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

from interfaces_backend.models.teleop import (
    TeleopStartRequest,
    TeleopStartResponse,
    TeleopSession,
    TeleopStopRequest,
    TeleopStopResponse,
    TeleopSessionsResponse,
    RemoteLeaderStartRequest,
    RemoteLeaderStartResponse,
    RemoteLeaderSession,
    RemoteFollowerStartRequest,
    RemoteFollowerStartResponse,
    RemoteFollowerSession,
    RemoteSessionsResponse,
)
from percus_ai.teleop import (
    SimpleTeleoperation,
    VisualTeleoperation,
    BimanualTeleoperation,
    RobotPreset,
)
from percus_ai.teleop.common import create_motor_bus, MotorState

router = APIRouter(prefix="/api/teleop", tags=["teleop"])

# In-memory session storage
_local_sessions: Dict[str, dict] = {}
_remote_leader_sessions: Dict[str, dict] = {}
_remote_follower_sessions: Dict[str, dict] = {}


# --- Local Teleoperation Endpoints ---


@router.post("/local/start", response_model=TeleopStartResponse)
async def start_local_teleop(request: TeleopStartRequest):
    """Start local teleoperation session.

    Creates a leader-follower teleoperation session where the follower
    arm mimics the leader arm movements.
    """
    session_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    # Select teleop class based on mode
    mode = request.mode.lower()
    if mode == "visual":
        TeleopClass = VisualTeleoperation
    elif mode == "bimanual":
        TeleopClass = BimanualTeleoperation
    else:
        TeleopClass = SimpleTeleoperation

    # Get robot preset
    preset = RobotPreset.SO101
    if request.robot_preset.lower() == "so100":
        preset = RobotPreset.SO100

    try:
        # Create teleop instance
        teleop = TeleopClass(
            leader_port=request.leader_port,
            follower_port=request.follower_port,
            fps=request.fps,
            robot_preset=preset,
        )

        # Store session info (but don't start yet in API - would need background task)
        session_data = {
            "session_id": session_id,
            "mode": mode,
            "leader_port": request.leader_port,
            "follower_port": request.follower_port,
            "fps": request.fps,
            "is_running": False,  # Would be True when actually running
            "started_at": now,
            "iterations": 0,
            "errors": 0,
            "teleop": teleop,
            "thread": None,
        }
        _local_sessions[session_id] = session_data

        return TeleopStartResponse(
            session=TeleopSession(
                session_id=session_id,
                mode=mode,
                leader_port=request.leader_port,
                follower_port=request.follower_port,
                fps=request.fps,
                is_running=False,
                started_at=now,
                iterations=0,
                errors=0,
            ),
            message="Teleop session created. Call /local/run to start.",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create teleop: {e}")


@router.post("/local/{session_id}/run")
async def run_local_teleop(session_id: str, duration_sec: Optional[float] = None):
    """Start running a teleop session.

    This runs the teleoperation loop in a background thread.
    """
    if session_id not in _local_sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    session = _local_sessions[session_id]

    if session.get("is_running"):
        return {"session_id": session_id, "message": "Already running"}

    teleop = session.get("teleop")
    if not teleop:
        raise HTTPException(status_code=500, detail="Teleop instance not found")

    def run_teleop():
        try:
            teleop.connect()
            session["is_running"] = True
            teleop.run(duration_sec=duration_sec)
        except Exception as e:
            session["errors"] = session.get("errors", 0) + 1
        finally:
            session["is_running"] = False
            try:
                teleop.disconnect()
            except Exception:
                pass

    thread = threading.Thread(target=run_teleop, daemon=True)
    thread.start()
    session["thread"] = thread

    return {"session_id": session_id, "message": "Teleop started"}


@router.post("/local/stop", response_model=TeleopStopResponse)
async def stop_local_teleop(request: TeleopStopRequest):
    """Stop a running teleoperation session."""
    session_id = request.session_id

    if session_id not in _local_sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    session = _local_sessions[session_id]
    teleop = session.get("teleop")

    # Stop teleop
    if teleop:
        try:
            teleop.disconnect()
        except Exception:
            pass

    # Calculate duration
    started_at = session.get("started_at", "")
    duration = 0.0
    if started_at:
        try:
            start = datetime.fromisoformat(started_at)
            duration = (datetime.now() - start).total_seconds()
        except Exception:
            pass

    iterations = session.get("iterations", 0)

    # Remove session
    del _local_sessions[session_id]

    return TeleopStopResponse(
        session_id=session_id,
        success=True,
        message="Teleop stopped",
        total_iterations=iterations,
        duration_seconds=duration,
    )


@router.get("/local/status/{session_id}", response_model=TeleopSession)
async def get_local_teleop_status(session_id: str):
    """Get status of a local teleoperation session."""
    if session_id not in _local_sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    s = _local_sessions[session_id]
    return TeleopSession(
        session_id=s["session_id"],
        mode=s.get("mode", "simple"),
        leader_port=s.get("leader_port", ""),
        follower_port=s.get("follower_port", ""),
        fps=s.get("fps", 60),
        is_running=s.get("is_running", False),
        started_at=s.get("started_at", ""),
        iterations=s.get("iterations", 0),
        errors=s.get("errors", 0),
    )


@router.get("/local/sessions", response_model=TeleopSessionsResponse)
async def list_local_teleop_sessions():
    """List all local teleoperation sessions."""
    sessions = [
        TeleopSession(
            session_id=s["session_id"],
            mode=s.get("mode", "simple"),
            leader_port=s.get("leader_port", ""),
            follower_port=s.get("follower_port", ""),
            fps=s.get("fps", 60),
            is_running=s.get("is_running", False),
            started_at=s.get("started_at", ""),
            iterations=s.get("iterations", 0),
            errors=s.get("errors", 0),
        )
        for s in _local_sessions.values()
    ]

    return TeleopSessionsResponse(sessions=sessions, total=len(sessions))


# --- Remote Teleoperation Endpoints ---


@router.post("/remote/leader/start", response_model=RemoteLeaderStartResponse)
async def start_remote_leader(request: RemoteLeaderStartRequest):
    """Start a remote leader server.

    The leader server streams arm positions and optionally camera frames
    to connected followers.
    """
    session_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    url = f"http://{request.host}:{request.port}"
    if request.host == "0.0.0.0":
        url = f"http://localhost:{request.port}"

    session_data = {
        "session_id": session_id,
        "host": request.host,
        "port": request.port,
        "url": url,
        "leader_port": request.leader_port,
        "camera_enabled": request.camera_id is not None,
        "is_running": False,
        "started_at": now,
        "clients_connected": 0,
        "server": None,
    }
    _remote_leader_sessions[session_id] = session_data

    # Note: Actual server start would require background process management
    # For now, just create the session

    return RemoteLeaderStartResponse(
        session=RemoteLeaderSession(
            session_id=session_id,
            host=request.host,
            port=request.port,
            url=url,
            leader_port=request.leader_port,
            camera_enabled=request.camera_id is not None,
            is_running=False,
            started_at=now,
            clients_connected=0,
        ),
        message="Leader session created. Use CLI to start server.",
    )


@router.post("/remote/leader/{session_id}/stop")
async def stop_remote_leader(session_id: str):
    """Stop a remote leader server."""
    if session_id not in _remote_leader_sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    session = _remote_leader_sessions[session_id]
    # Stop server if running
    server = session.get("server")
    if server:
        try:
            # Would need proper shutdown mechanism
            pass
        except Exception:
            pass

    del _remote_leader_sessions[session_id]
    return {"session_id": session_id, "message": "Leader stopped"}


@router.get("/remote/leader/status/{session_id}", response_model=RemoteLeaderSession)
async def get_remote_leader_status(session_id: str):
    """Get status of a remote leader server."""
    if session_id not in _remote_leader_sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    s = _remote_leader_sessions[session_id]
    return RemoteLeaderSession(
        session_id=s["session_id"],
        host=s.get("host", ""),
        port=s.get("port", 0),
        url=s.get("url", ""),
        leader_port=s.get("leader_port", ""),
        camera_enabled=s.get("camera_enabled", False),
        is_running=s.get("is_running", False),
        started_at=s.get("started_at", ""),
        clients_connected=s.get("clients_connected", 0),
    )


@router.post("/remote/follower/start", response_model=RemoteFollowerStartResponse)
async def start_remote_follower(request: RemoteFollowerStartRequest):
    """Start a remote follower client.

    Connects to a leader server and syncs the follower arm.
    """
    session_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    session_data = {
        "session_id": session_id,
        "leader_url": request.leader_url,
        "follower_port": request.follower_port,
        "is_connected": False,
        "is_running": False,
        "started_at": now,
        "latency_ms": 0.0,
        "sync_errors": 0,
        "client": None,
    }
    _remote_follower_sessions[session_id] = session_data

    return RemoteFollowerStartResponse(
        session=RemoteFollowerSession(
            session_id=session_id,
            leader_url=request.leader_url,
            follower_port=request.follower_port,
            is_connected=False,
            is_running=False,
            started_at=now,
            latency_ms=0.0,
            sync_errors=0,
        ),
        message="Follower session created. Use CLI to start client.",
    )


@router.post("/remote/follower/{session_id}/stop")
async def stop_remote_follower(session_id: str):
    """Stop a remote follower client."""
    if session_id not in _remote_follower_sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    session = _remote_follower_sessions[session_id]
    client = session.get("client")
    if client:
        try:
            pass  # Would need proper shutdown
        except Exception:
            pass

    del _remote_follower_sessions[session_id]
    return {"session_id": session_id, "message": "Follower stopped"}


@router.get("/remote/follower/status/{session_id}", response_model=RemoteFollowerSession)
async def get_remote_follower_status(session_id: str):
    """Get status of a remote follower client."""
    if session_id not in _remote_follower_sessions:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    s = _remote_follower_sessions[session_id]
    return RemoteFollowerSession(
        session_id=s["session_id"],
        leader_url=s.get("leader_url", ""),
        follower_port=s.get("follower_port", ""),
        is_connected=s.get("is_connected", False),
        is_running=s.get("is_running", False),
        started_at=s.get("started_at", ""),
        latency_ms=s.get("latency_ms", 0.0),
        sync_errors=s.get("sync_errors", 0),
    )


@router.get("/remote/sessions", response_model=RemoteSessionsResponse)
async def list_remote_sessions():
    """List all remote teleoperation sessions."""
    leaders = [
        RemoteLeaderSession(
            session_id=s["session_id"],
            host=s.get("host", ""),
            port=s.get("port", 0),
            url=s.get("url", ""),
            leader_port=s.get("leader_port", ""),
            camera_enabled=s.get("camera_enabled", False),
            is_running=s.get("is_running", False),
            started_at=s.get("started_at", ""),
            clients_connected=s.get("clients_connected", 0),
        )
        for s in _remote_leader_sessions.values()
    ]

    followers = [
        RemoteFollowerSession(
            session_id=s["session_id"],
            leader_url=s.get("leader_url", ""),
            follower_port=s.get("follower_port", ""),
            is_connected=s.get("is_connected", False),
            is_running=s.get("is_running", False),
            started_at=s.get("started_at", ""),
            latency_ms=s.get("latency_ms", 0.0),
            sync_errors=s.get("sync_errors", 0),
        )
        for s in _remote_follower_sessions.values()
    ]

    return RemoteSessionsResponse(leaders=leaders, followers=followers)


# --- WebSocket Visual Teleoperation ---


@router.websocket("/ws/visual")
async def websocket_visual_teleop(websocket: WebSocket):
    """WebSocket endpoint for visual teleoperation with real-time motor state streaming.

    Client sends JSON messages:
    - {"action": "start", "leader_port": "/dev/ttyACM0", "follower_port": "/dev/ttyACM1",
       "robot_preset": "so101", "fps": 60}
    - {"action": "stop"}

    Server sends JSON messages:
    - {"type": "state", "leader_states": {...}, "follower_states": {...},
       "iteration": N, "elapsed": X.X, "actual_fps": Y.Y, "errors": N}
    - {"type": "connected", "message": "..."}
    - {"type": "stopped", "message": "..."}
    - {"type": "error", "error": "..."}
    """
    await websocket.accept()
    logger.info("Visual teleop WebSocket connected")

    leader_bus = None
    follower_bus = None
    running = False
    stop_requested = False

    def read_motor_state(bus, motor_name: str) -> dict:
        """Read motor state from bus and return as dict."""
        state = {"error": None}
        try:
            state["position"] = bus.read("Present_Position", motor_name, normalize=False)
            try:
                state["load"] = bus.read("Present_Load", motor_name, normalize=False)
            except Exception:
                state["load"] = None
            try:
                state["temperature"] = bus.read("Present_Temperature", motor_name, normalize=False)
            except Exception:
                state["temperature"] = None
            try:
                voltage = bus.read("Present_Voltage", motor_name, normalize=False)
                state["voltage"] = voltage / 10.0 if voltage is not None else None
            except Exception:
                state["voltage"] = None
            try:
                state["speed"] = bus.read("Present_Velocity", motor_name, normalize=False)
            except Exception:
                state["speed"] = None
            try:
                state["current"] = bus.read("Present_Current", motor_name, normalize=False)
            except Exception:
                state["current"] = None
        except Exception as e:
            state["error"] = str(e)
        return state

    try:
        while True:
            # Wait for message with timeout to allow checking stop flag
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=0.05)
            except asyncio.TimeoutError:
                # No message, continue loop if running
                if running and not stop_requested:
                    # Read and send motor states
                    loop_start = time.time()

                    leader_states = {}
                    follower_states = {}
                    errors_count = 0

                    for motor_name in leader_bus.motors.keys():
                        leader_states[motor_name] = read_motor_state(leader_bus, motor_name)
                        if leader_states[motor_name].get("error"):
                            errors_count += 1

                    for motor_name in leader_bus.motors.keys():
                        leader_state = leader_states[motor_name]
                        if leader_state.get("position") is not None and not leader_state.get("error"):
                            try:
                                follower_bus.write(
                                    "Goal_Position",
                                    motor_name,
                                    leader_state["position"],
                                    normalize=False,
                                )
                            except Exception:
                                errors_count += 1

                        follower_states[motor_name] = read_motor_state(follower_bus, motor_name)
                        if follower_states[motor_name].get("error"):
                            errors_count += 1

                    iteration += 1
                    elapsed = time.time() - start_time
                    actual_fps = iteration / elapsed if elapsed > 0 else 0

                    await websocket.send_json({
                        "type": "state",
                        "leader_states": leader_states,
                        "follower_states": follower_states,
                        "iteration": iteration,
                        "elapsed": elapsed,
                        "actual_fps": actual_fps,
                        "target_fps": target_fps,
                        "errors": errors_count,
                    })

                    # Maintain control frequency
                    loop_time = time.time() - loop_start
                    sleep_time = dt - loop_time
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)

                continue

            action = data.get("action")

            if action == "start":
                if running:
                    await websocket.send_json({
                        "type": "error",
                        "error": "Already running. Stop first.",
                    })
                    continue

                leader_port = data.get("leader_port")
                follower_port = data.get("follower_port")
                robot_preset_str = data.get("robot_preset", "so101")
                target_fps = data.get("fps", 60)
                dt = 1.0 / target_fps

                preset = RobotPreset.SO101
                if robot_preset_str.lower() == "so100":
                    preset = RobotPreset.SO100

                try:
                    leader_bus = create_motor_bus(leader_port, preset)
                    follower_bus = create_motor_bus(follower_port, preset)

                    leader_bus.connect()
                    follower_bus.connect()

                    motor_names = list(leader_bus.motors.keys())

                    await websocket.send_json({
                        "type": "connected",
                        "message": f"Connected to both arms. Motors: {motor_names}",
                        "motor_names": motor_names,
                    })

                    running = True
                    stop_requested = False
                    iteration = 0
                    start_time = time.time()

                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "error": f"Failed to connect: {e}",
                    })
                    # Cleanup
                    if leader_bus:
                        try:
                            leader_bus.disconnect()
                        except Exception:
                            pass
                        leader_bus = None
                    if follower_bus:
                        try:
                            follower_bus.disconnect()
                        except Exception:
                            pass
                        follower_bus = None

            elif action == "stop":
                if running:
                    stop_requested = True
                    running = False

                    # Disconnect
                    if leader_bus:
                        try:
                            leader_bus.disconnect()
                        except Exception:
                            pass
                        leader_bus = None
                    if follower_bus:
                        try:
                            follower_bus.disconnect()
                        except Exception:
                            pass
                        follower_bus = None

                    elapsed = time.time() - start_time if start_time else 0
                    await websocket.send_json({
                        "type": "stopped",
                        "message": "Teleoperation stopped",
                        "total_iterations": iteration,
                        "duration": elapsed,
                        "average_fps": iteration / elapsed if elapsed > 0 else 0,
                    })
                else:
                    await websocket.send_json({
                        "type": "error",
                        "error": "Not running",
                    })

            else:
                await websocket.send_json({
                    "type": "error",
                    "error": f"Unknown action: {action}",
                })

    except WebSocketDisconnect:
        logger.info("Visual teleop WebSocket disconnected")
    except Exception as e:
        logger.error(f"Visual teleop WebSocket error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "error": str(e),
            })
        except Exception:
            pass
    finally:
        # Cleanup
        if leader_bus:
            try:
                leader_bus.disconnect()
            except Exception:
                pass
        if follower_bus:
            try:
                follower_bus.disconnect()
            except Exception:
                pass
        logger.info("Visual teleop WebSocket cleanup complete")
