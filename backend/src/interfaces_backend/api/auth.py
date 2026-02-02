"""Authentication API router."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from interfaces_backend.models.auth import (
    AuthLoginRequest,
    AuthLoginResponse,
    AuthStatusResponse,
    AuthTokenResponse,
)
from interfaces_backend.core.request_auth import (
    ACCESS_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    REFRESH_ISSUED_AT_COOKIE_NAME,
    build_session_from_request,
    compute_session_expires_at,
    clear_session_cookies,
    get_session_expires_at_from_request,
    is_session_expired,
    needs_session_cookie_update,
    refresh_session_from_request,
    set_session_cookies,
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


@router.post("/login", response_model=AuthLoginResponse)
async def login(request: AuthLoginRequest, response: Response, http_request: Request) -> AuthLoginResponse:
    client = await create_supabase_anon_client()
    supabase_response = await client.auth.sign_in_with_password(
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

    session_payload = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "user_id": user_id,
    }
    set_session_cookies(response, session_payload)
    session_expires_at = None
    if refresh_token:
        session_expires_at = compute_session_expires_at(int(time.time()))

    is_cli = http_request.headers.get("x-client") == "cli"
    return AuthLoginResponse(
        success=True,
        user_id=user_id,
        expires_at=expires_at,
        session_expires_at=session_expires_at,
        access_token=access_token if is_cli else None,
        refresh_token=refresh_token if is_cli else None,
    )


@router.post("/logout", response_model=AuthStatusResponse)
def logout(response: Response) -> AuthStatusResponse:
    response.delete_cookie(ACCESS_COOKIE_NAME, path="/")
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
    response.delete_cookie(REFRESH_ISSUED_AT_COOKIE_NAME, path="/")
    return AuthStatusResponse(authenticated=False, user_id=None, expires_at=None)


@router.get("/status", response_model=AuthStatusResponse)
def status(http_request: Request, response: Response) -> AuthStatusResponse:
    session = build_session_from_request(http_request)
    if not session or is_session_expired(session):
        session_expires_at = get_session_expires_at_from_request(http_request)
        return AuthStatusResponse(
            authenticated=False,
            user_id=None,
            expires_at=None,
            session_expires_at=session_expires_at,
        )
    session_expires_at = None
    if session.get("refresh_token"):
        if needs_session_cookie_update(http_request):
            session_expires_at = compute_session_expires_at(int(time.time()))
            set_session_cookies(response, session)
        else:
            session_expires_at = get_session_expires_at_from_request(http_request)
    return AuthStatusResponse(
        authenticated=True,
        user_id=session.get("user_id"),
        expires_at=session.get("expires_at"),
        session_expires_at=session_expires_at,
    )


@router.get("/token", response_model=AuthTokenResponse)
def token(http_request: Request, response: Response) -> AuthTokenResponse:
    session = build_session_from_request(http_request)
    if not session or is_session_expired(session):
        raise HTTPException(status_code=401, detail="unauthenticated")
    access_token = session.get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail="unauthenticated")
    session_expires_at = None
    if session.get("refresh_token"):
        if refreshed or needs_session_cookie_update(http_request):
            session_expires_at = compute_session_expires_at(int(time.time()))
            set_session_cookies(response, session)
        else:
            session_expires_at = get_session_expires_at_from_request(http_request)
    return AuthTokenResponse(
        access_token=access_token,
        refresh_token=session.get("refresh_token"),
        user_id=session.get("user_id"),
        expires_at=session.get("expires_at"),
        session_expires_at=session_expires_at,
    )


@router.post("/refresh", response_model=AuthStatusResponse)
def refresh(http_request: Request, response: Response) -> AuthStatusResponse:
    session = refresh_session_from_request(http_request)
    if not session:
        clear_session_cookies(response)
        raise HTTPException(status_code=401, detail="unauthenticated")
    set_session_cookies(response, session)
    session_expires_at = None
    if session.get("refresh_token"):
        session_expires_at = compute_session_expires_at(int(time.time()))
    return AuthStatusResponse(
        authenticated=True,
        user_id=session.get("user_id"),
        expires_at=session.get("expires_at"),
        session_expires_at=session_expires_at,
    )
