"""Request-scoped auth helpers (Cookie/Bearer)."""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from fastapi import Request, Response

ACCESS_COOKIE_NAME = "phi_access_token"
REFRESH_COOKIE_NAME = "phi_refresh_token"
REFRESH_ISSUED_AT_COOKIE_NAME = "phi_refresh_issued_at"
DEFAULT_REFRESH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7
DEFAULT_SUPABASE_REFRESH_TIMEOUT_SECONDS = 3

logger = logging.getLogger(__name__)


def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload_b64 = parts[1]
    padding = "=" * (-len(payload_b64) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload_b64 + padding)
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _get_supabase_auth_config() -> tuple[str, str] | None:
    url = os.environ.get("SUPABASE_URL")
    secret_key = os.environ.get("SUPABASE_SECRET_KEY")
    anon_key = os.environ.get("SUPABASE_ANON_KEY")
    api_key = secret_key or anon_key
    if not url or not api_key:
        return None
    return url.rstrip("/"), api_key


def _access_cookie_max_age(expires_at: Any) -> Optional[int]:
    if not expires_at:
        return None
    try:
        return max(0, int(float(expires_at) - time.time()))
    except (TypeError, ValueError):
        return None


def _refresh_cookie_max_age() -> int:
    raw = os.environ.get("PHI_REFRESH_COOKIE_MAX_AGE_SECONDS")
    if raw is None or raw == "":
        return DEFAULT_REFRESH_COOKIE_MAX_AGE_SECONDS
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_REFRESH_COOKIE_MAX_AGE_SECONDS


def _refresh_timeout_seconds() -> int:
    raw = os.environ.get("PHI_SUPABASE_REFRESH_TIMEOUT_SECONDS")
    if raw is None or raw == "":
        return DEFAULT_SUPABASE_REFRESH_TIMEOUT_SECONDS
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_SUPABASE_REFRESH_TIMEOUT_SECONDS


def set_session_cookies(response: Response, session: dict[str, Any]) -> None:
    access_token = session.get("access_token")
    if not access_token:
        return
    refresh_max_age = _refresh_cookie_max_age()
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        access_token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=_access_cookie_max_age(session.get("expires_at")),
    )
    refresh_token = session.get("refresh_token")
    if refresh_token:
        response.set_cookie(
            REFRESH_COOKIE_NAME,
            refresh_token,
            httponly=True,
            samesite="lax",
            path="/",
            max_age=refresh_max_age,
        )
        response.set_cookie(
            REFRESH_ISSUED_AT_COOKIE_NAME,
            str(int(time.time())),
            httponly=True,
            samesite="lax",
            path="/",
            max_age=refresh_max_age,
        )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE_NAME, path="/")
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
    response.delete_cookie(REFRESH_ISSUED_AT_COOKIE_NAME, path="/")


def extract_access_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("authorization")
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
    cookie_token = request.cookies.get(ACCESS_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    return None


def extract_refresh_token(request: Request) -> Optional[str]:
    return request.cookies.get(REFRESH_COOKIE_NAME)


def build_session_from_tokens(
    access_token: Optional[str],
    refresh_token: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    if not access_token:
        return None
    payload = _decode_jwt_payload(access_token) or {}
    user_id = payload.get("sub")
    expires_at = payload.get("exp")
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "user_id": user_id,
    }


def compute_session_expires_at(issued_at: int) -> int:
    return issued_at + _refresh_cookie_max_age()


def get_session_expires_at_from_request(request: Request) -> Optional[int]:
    issued_at_raw = request.cookies.get(REFRESH_ISSUED_AT_COOKIE_NAME)
    if not issued_at_raw:
        return None
    try:
        issued_at = int(float(issued_at_raw))
    except (TypeError, ValueError):
        return None
    return compute_session_expires_at(issued_at)


def needs_session_cookie_update(request: Request) -> bool:
    if not request.cookies.get(REFRESH_COOKIE_NAME):
        return False
    issued_at_raw = request.cookies.get(REFRESH_ISSUED_AT_COOKIE_NAME)
    if not issued_at_raw:
        return True
    try:
        int(float(issued_at_raw))
    except (TypeError, ValueError):
        return True
    return False


def is_session_expired(session: Optional[dict[str, Any]], leeway_seconds: int = 30) -> bool:
    if not session:
        return True
    expires_at = session.get("expires_at")
    if not expires_at:
        return False
    try:
        return time.time() >= float(expires_at) - leeway_seconds
    except (TypeError, ValueError):
        return False


def _refresh_session(refresh_token: str) -> Optional[dict[str, Any]]:
    config = _get_supabase_auth_config()
    if not config:
        return None
    url, api_key = config
    payload = json.dumps({"refresh_token": refresh_token}).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/auth/v1/token?grant_type=refresh_token",
        data=payload,
        method="POST",
    )
    req.add_header("apikey", api_key)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=_refresh_timeout_seconds()) as resp:
            data = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8")
        except Exception:
            body = ""
        logger.warning("Supabase refresh failed: %s %s", exc, body)
        return None
    except Exception as exc:
        logger.warning("Supabase refresh error: %s", exc)
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    access_token = payload.get("access_token")
    if not access_token:
        return None
    new_refresh = payload.get("refresh_token") or refresh_token
    user_id = None
    user = payload.get("user")
    if isinstance(user, dict):
        user_id = user.get("id")
    if not user_id:
        user_id = (_decode_jwt_payload(access_token) or {}).get("sub")
    expires_at = payload.get("expires_at")
    if not expires_at:
        expires_at = (_decode_jwt_payload(access_token) or {}).get("exp")
    return {
        "access_token": access_token,
        "refresh_token": new_refresh,
        "expires_at": expires_at,
        "user_id": user_id,
    }


def build_session_from_request(request: Request) -> Optional[dict[str, Any]]:
    access_token = extract_access_token(request)
    refresh_token = extract_refresh_token(request)
    return build_session_from_tokens(access_token, refresh_token)


def refresh_session_from_request(request: Request) -> Optional[dict[str, Any]]:
    refresh_token = extract_refresh_token(request)
    if not refresh_token:
        return None
    return _refresh_session(refresh_token)


def refresh_session_from_refresh_token(
    refresh_token: Optional[str],
) -> Optional[dict[str, Any]]:
    if not refresh_token:
        return None
    return _refresh_session(refresh_token)
