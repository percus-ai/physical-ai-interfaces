"""Teleop session control API."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter

from interfaces_backend.api.profiles import _get_vlabor_status
from interfaces_backend.models.teleop import (
    TeleopSessionActionResponse,
    TeleopSessionCreateRequest,
    TeleopSessionStartRequest,
    TeleopSessionStatusResponse,
    TeleopSessionStopRequest,
)
from interfaces_backend.services.session_manager import require_user_id
from interfaces_backend.services.teleop_session import get_teleop_session_manager

router = APIRouter(prefix="/api/teleop", tags=["teleop"])

_SESSION_ID = "teleop"


def _status_payload() -> dict[str, Any]:
    return dict(_get_vlabor_status())


@router.post("/session/create", response_model=TeleopSessionActionResponse)
async def create_session(request: Optional[TeleopSessionCreateRequest] = None):
    require_user_id()
    payload = request or TeleopSessionCreateRequest()
    mgr = get_teleop_session_manager()
    state = await mgr.create(
        profile=payload.profile,
        domain_id=payload.domain_id,
        dev_mode=payload.dev_mode,
    )
    message = (
        "Teleop session already running" if state.status == "running" else "Teleop session created"
    )
    return TeleopSessionActionResponse(
        success=True,
        session_id=state.id,
        message=message,
        status=_status_payload(),
    )


@router.post("/session/start", response_model=TeleopSessionActionResponse)
async def start_session(request: TeleopSessionStartRequest):
    require_user_id()
    mgr = get_teleop_session_manager()
    state = await mgr.start(request.session_id)
    return TeleopSessionActionResponse(
        success=True,
        session_id=state.id,
        message="Teleop session started",
        status=_status_payload(),
    )


@router.post("/session/stop", response_model=TeleopSessionActionResponse)
async def stop_session(request: Optional[TeleopSessionStopRequest] = None):
    require_user_id()
    session_id = (request.session_id if request else None) or _SESSION_ID
    mgr = get_teleop_session_manager()
    state = await mgr.stop(session_id)
    return TeleopSessionActionResponse(
        success=True,
        session_id=state.id,
        message="Teleop session stopped",
        status=_status_payload(),
    )


@router.get("/session/status", response_model=TeleopSessionStatusResponse)
async def get_session_status():
    require_user_id()
    mgr = get_teleop_session_manager()
    session = mgr.status(_SESSION_ID)
    status = _status_payload()
    vlabor_running = (status.get("status") or "") == "running"

    if session:
        state = session.status or "created"
        if vlabor_running and state != "running":
            state = "running"
        if not vlabor_running and state == "running":
            state = "stopped"
        return TeleopSessionStatusResponse(
            active=bool(vlabor_running and state == "running"),
            session_id=session.id,
            state=state,
            created_at=session.created_at,
            started_at=session.started_at,
            profile=session.profile.name if session.profile else None,
            domain_id=session.extras.get("domain_id"),
            dev_mode=bool(session.extras.get("dev_mode")),
            status=status,
        )

    return TeleopSessionStatusResponse(
        active=vlabor_running,
        session_id=_SESSION_ID if vlabor_running else None,
        state="running" if vlabor_running else "stopped",
        status=status,
    )
