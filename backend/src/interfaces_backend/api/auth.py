"""Authentication API router."""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from interfaces_backend.core.auth import (
    clear_supabase_session_file,
    get_cached_supabase_session,
    load_supabase_session,
    save_supabase_session,
)
from interfaces_backend.models.auth import (
    AuthLoginRequest,
    AuthLoginResponse,
    AuthStatusResponse,
)
from percus_ai.db import create_supabase_anon_client

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _extract_value(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _extract_session(response: Any) -> Any:
    session = _extract_value(response, "session")
    if session is not None:
        return session
    data = _extract_value(response, "data")
    return _extract_value(data, "session")


def _extract_user_id(response: Any, session: Any) -> str | None:
    user = _extract_value(response, "user") or _extract_value(session, "user")
    return _extract_value(user, "id")


def _is_session_expired(session: Optional[dict[str, Any]]) -> bool:
    if not session:
        return True
    expires_at = session.get("expires_at")
    if not expires_at:
        return False
    try:
        return time.time() >= float(expires_at) - 30
    except (TypeError, ValueError):
        return False


@router.post("/login", response_model=AuthLoginResponse)
def login(request: AuthLoginRequest) -> AuthLoginResponse:
    client = create_supabase_anon_client()
    response = client.auth.sign_in_with_password(
        {"email": request.email, "password": request.password}
    )
    session = _extract_session(response)
    if session is None:
        raise HTTPException(status_code=401, detail="Login failed")

    access_token = _extract_value(session, "access_token")
    refresh_token = _extract_value(session, "refresh_token")
    expires_at = _extract_value(session, "expires_at")
    user_id = _extract_user_id(response, session)

    if not access_token or not user_id:
        raise HTTPException(status_code=401, detail="Login failed")

    payload = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "user_id": user_id,
    }
    save_supabase_session(payload)

    return AuthLoginResponse(success=True, user_id=user_id, expires_at=expires_at)


@router.post("/logout", response_model=AuthStatusResponse)
def logout() -> AuthStatusResponse:
    clear_supabase_session_file()
    return AuthStatusResponse(authenticated=False, user_id=None, expires_at=None)


@router.get("/status", response_model=AuthStatusResponse)
def status() -> AuthStatusResponse:
    session = get_cached_supabase_session() or load_supabase_session()
    if not session or _is_session_expired(session):
        clear_supabase_session_file()
        return AuthStatusResponse(authenticated=False, user_id=None, expires_at=None)
    return AuthStatusResponse(
        authenticated=True,
        user_id=session.get("user_id"),
        expires_at=session.get("expires_at"),
    )
