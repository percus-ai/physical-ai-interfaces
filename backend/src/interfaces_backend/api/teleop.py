"""Teleoperation API router."""

import sys
import uuid
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException

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

router = APIRouter(prefix="/api/teleop", tags=["teleop"])

# In-memory session storage
_local_sessions: Dict[str, dict] = {}
_remote_leader_sessions: Dict[str, dict] = {}
_remote_follower_sessions: Dict[str, dict] = {}


def _get_teleop_module():
    """Import percus_ai.teleop if available."""
    try:
        from percus_ai.teleop import (
            SimpleTeleoperation,
            VisualTeleoperation,
            BimanualTeleoperation,
            RobotPreset,
        )
        return SimpleTeleoperation, VisualTeleoperation, BimanualTeleoperation, RobotPreset
    except ImportError:
        features_path = Path(__file__).resolve().parents[5] / "features"
        if features_path.exists() and str(features_path) not in sys.path:
            sys.path.insert(0, str(features_path))
            try:
                from percus_ai.teleop import (
                    SimpleTeleoperation,
                    VisualTeleoperation,
                    BimanualTeleoperation,
                    RobotPreset,
                )
                return SimpleTeleoperation, VisualTeleoperation, BimanualTeleoperation, RobotPreset
            except ImportError:
                pass
    return None, None, None, None


def _get_remote_teleop():
    """Import percus_ai.teleop.remote if available."""
    try:
        from percus_ai.teleop.remote import run_leader_server, run_follower_server
        return run_leader_server, run_follower_server
    except ImportError:
        features_path = Path(__file__).resolve().parents[5] / "features"
        if features_path.exists() and str(features_path) not in sys.path:
            sys.path.insert(0, str(features_path))
            try:
                from percus_ai.teleop.remote import run_leader_server, run_follower_server
                return run_leader_server, run_follower_server
            except ImportError:
                pass
    return None, None


# --- Local Teleoperation Endpoints ---


@router.post("/local/start", response_model=TeleopStartResponse)
async def start_local_teleop(request: TeleopStartRequest):
    """Start local teleoperation session.

    Creates a leader-follower teleoperation session where the follower
    arm mimics the leader arm movements.
    """
    SimpleTeleop, VisualTeleop, BimanualTeleop, RobotPreset = _get_teleop_module()

    if not SimpleTeleop:
        raise HTTPException(
            status_code=503,
            detail="Teleoperation module not available. Install percus_ai[teleop].",
        )

    session_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    # Select teleop class based on mode
    mode = request.mode.lower()
    if mode == "visual":
        TeleopClass = VisualTeleop
    elif mode == "bimanual":
        TeleopClass = BimanualTeleop
    else:
        TeleopClass = SimpleTeleop

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
    run_leader, _ = _get_remote_teleop()

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
    _, run_follower = _get_remote_teleop()

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
