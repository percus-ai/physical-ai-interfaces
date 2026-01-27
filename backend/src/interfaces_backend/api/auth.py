"""Authentication API router."""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from interfaces_backend.models.auth import (
    AuthLoginRequest,
    AuthLoginResponse,
    AuthStatusResponse,
)
from interfaces_backend.core.request_auth import (
    ACCESS_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    build_session_from_request,
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
def login(request: AuthLoginRequest, response: Response, http_request: Request) -> AuthLoginResponse:
    client = create_supabase_anon_client()
    supabase_response = client.auth.sign_in_with_password(
        {"email": request.email, "password": request.password}
    )
    session = _extract_session(supabase_response)
    if session is None:
        raise HTTPException(status_code=401, detail="Login failed")

    access_token = _extract_value(session, "access_token")
    refresh_token = _extract_value(session, "refresh_token")
    expires_at = _extract_value(session, "expires_at")
    user_id = _extract_user_id(supabase_response, session)

    if not access_token or not user_id:
        raise HTTPException(status_code=401, detail="Login failed")

    max_age = None
    if expires_at:
        try:
            max_age = max(0, int(float(expires_at) - time.time()))
        except (TypeError, ValueError):
            max_age = None

    response.set_cookie(
        ACCESS_COOKIE_NAME,
        access_token,
        httponly=True,
        samesite="lax",
        max_age=max_age,
    )
    if refresh_token:
        response.set_cookie(
            REFRESH_COOKIE_NAME,
            refresh_token,
            httponly=True,
            samesite="lax",
            max_age=max_age,
        )

    is_cli = http_request.headers.get("x-client") == "cli"
    return AuthLoginResponse(
        success=True,
        user_id=user_id,
        expires_at=expires_at,
        access_token=access_token if is_cli else None,
        refresh_token=refresh_token if is_cli else None,
    )


@router.post("/logout", response_model=AuthStatusResponse)
def logout(response: Response) -> AuthStatusResponse:
    response.delete_cookie(ACCESS_COOKIE_NAME)
    response.delete_cookie(REFRESH_COOKIE_NAME)
    return AuthStatusResponse(authenticated=False, user_id=None, expires_at=None)


@router.get("/status", response_model=AuthStatusResponse)
def status(http_request: Request) -> AuthStatusResponse:
    session = build_session_from_request(http_request)
    if not session or _is_session_expired(session):
        return AuthStatusResponse(authenticated=False, user_id=None, expires_at=None)
    return AuthStatusResponse(
        authenticated=True,
        user_id=session.get("user_id"),
        expires_at=session.get("expires_at"),
    )
