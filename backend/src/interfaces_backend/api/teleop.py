"""Teleop session control API."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from interfaces_backend.api.profiles import _get_vlabor_status
from interfaces_backend.models.teleop import (
    TeleopSessionActionResponse,
    TeleopSessionCreateRequest,
    TeleopSessionStartRequest,
    TeleopSessionStatusResponse,
    TeleopSessionStopRequest,
)
from interfaces_backend.services.lerobot_runtime import (
    LerobotCommandError,
    start_lerobot,
    stop_lerobot,
)
from interfaces_backend.services.vlabor_runtime import (
    VlaborCommandError,
    start_vlabor as run_vlabor_start,
    stop_vlabor as run_vlabor_stop,
)
from interfaces_backend.services.vlabor_profiles import (
    get_active_profile_spec,
    resolve_profile_spec,
    save_session_profile_binding,
)
from percus_ai.db import get_current_user_id

router = APIRouter(prefix="/api/teleop", tags=["teleop"])

_SESSION_ID = "teleop"
_SESSION_LOCK = threading.RLock()
_ACTIVE_SESSION: dict[str, Any] | None = None


def _require_user_id() -> str:
    try:
        return get_current_user_id()
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Login required") from exc


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_payload() -> dict[str, Any]:
    return dict(_get_vlabor_status())


def _active_session_copy() -> dict[str, Any] | None:
    with _SESSION_LOCK:
        return dict(_ACTIVE_SESSION) if _ACTIVE_SESSION else None


@router.post("/session/create", response_model=TeleopSessionActionResponse)
async def create_session(request: Optional[TeleopSessionCreateRequest] = None):
    _require_user_id()
    payload = request or TeleopSessionCreateRequest()
    profile = resolve_profile_spec(payload.profile) if payload.profile else await get_active_profile_spec()
    try:
        run_vlabor_start(profile=profile.name, domain_id=payload.domain_id, dev_mode=payload.dev_mode)
    except VlaborCommandError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create teleop session: {exc}") from exc
    try:
        start_lerobot(strict=True)
    except LerobotCommandError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start lerobot stack: {exc}") from exc
    await save_session_profile_binding(session_kind="teleop", session_id=_SESSION_ID, profile=profile)

    now = _now_iso()
    with _SESSION_LOCK:
        global _ACTIVE_SESSION
        if _ACTIVE_SESSION and _ACTIVE_SESSION.get("state") == "running":
            return TeleopSessionActionResponse(
                success=True,
                session_id=_SESSION_ID,
                message="Teleop session already running",
                status=_status_payload(),
            )
        _ACTIVE_SESSION = {
            "session_id": _SESSION_ID,
            "state": "created",
            "created_at": now,
            "started_at": _ACTIVE_SESSION.get("started_at") if _ACTIVE_SESSION else None,
            "profile": profile.name,
            "profile_snapshot": profile.snapshot,
            "domain_id": payload.domain_id,
            "dev_mode": bool(payload.dev_mode),
        }

    return TeleopSessionActionResponse(
        success=True,
        session_id=_SESSION_ID,
        message="Teleop session created",
        status=_status_payload(),
    )


@router.post("/session/start", response_model=TeleopSessionActionResponse)
async def start_session(request: TeleopSessionStartRequest):
    _require_user_id()
    if request.session_id != _SESSION_ID:
        raise HTTPException(status_code=404, detail=f"Teleop session not found: {request.session_id}")

    session = _active_session_copy()
    if not session:
        raise HTTPException(status_code=404, detail="Teleop session not found. Create session first.")

    try:
        run_vlabor_start(
            profile=session.get("profile"),
            domain_id=session.get("domain_id"),
            dev_mode=bool(session.get("dev_mode")),
        )
    except VlaborCommandError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start teleop session: {exc}") from exc
    try:
        start_lerobot(strict=True)
    except LerobotCommandError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start lerobot stack: {exc}") from exc

    with _SESSION_LOCK:
        if _ACTIVE_SESSION is None:
            raise HTTPException(status_code=404, detail="Teleop session not found")
        _ACTIVE_SESSION["state"] = "running"
        _ACTIVE_SESSION["started_at"] = _ACTIVE_SESSION.get("started_at") or _now_iso()

    return TeleopSessionActionResponse(
        success=True,
        session_id=_SESSION_ID,
        message="Teleop session started",
        status=_status_payload(),
    )


@router.post("/session/stop", response_model=TeleopSessionActionResponse)
async def stop_session(request: Optional[TeleopSessionStopRequest] = None):
    _require_user_id()
    session_id = (request.session_id if request else None) or _SESSION_ID
    if session_id != _SESSION_ID:
        raise HTTPException(status_code=404, detail=f"Teleop session not found: {session_id}")

    try:
        run_vlabor_stop()
    except VlaborCommandError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to stop teleop session: {exc}") from exc
    stop_lerobot(strict=False)

    with _SESSION_LOCK:
        global _ACTIVE_SESSION
        _ACTIVE_SESSION = None

    return TeleopSessionActionResponse(
        success=True,
        session_id=_SESSION_ID,
        message="Teleop session stopped",
        status=_status_payload(),
    )


@router.get("/session/status", response_model=TeleopSessionStatusResponse)
async def get_session_status():
    _require_user_id()
    session = _active_session_copy()
    status = _status_payload()
    vlabor_running = (status.get("status") or "") == "running"

    if session:
        state = session.get("state") or "created"
        if vlabor_running and state != "running":
            state = "running"
        if not vlabor_running and state == "running":
            state = "stopped"
        return TeleopSessionStatusResponse(
            active=bool(vlabor_running and state == "running"),
            session_id=session.get("session_id"),
            state=state,
            created_at=session.get("created_at"),
            started_at=session.get("started_at"),
            profile=session.get("profile"),
            domain_id=session.get("domain_id"),
            dev_mode=bool(session.get("dev_mode")),
            status=status,
        )

    return TeleopSessionStatusResponse(
        active=vlabor_running,
        session_id=_SESSION_ID if vlabor_running else None,
        state="running" if vlabor_running else "stopped",
        status=status,
    )
