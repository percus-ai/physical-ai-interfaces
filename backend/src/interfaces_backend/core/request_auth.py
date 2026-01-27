"""Request-scoped auth helpers (Cookie/Bearer)."""

from __future__ import annotations

import base64
import json
from typing import Any, Optional

from fastapi import Request

ACCESS_COOKIE_NAME = "phi_access_token"
REFRESH_COOKIE_NAME = "phi_refresh_token"


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


def build_session_from_request(request: Request) -> Optional[dict[str, Any]]:
    access_token = extract_access_token(request)
    if not access_token:
        return None
    payload = _decode_jwt_payload(access_token) or {}
    user_id = payload.get("sub")
    expires_at = payload.get("exp")
    session = {
        "access_token": access_token,
        "refresh_token": extract_refresh_token(request),
        "expires_at": expires_at,
        "user_id": user_id,
    }
    return session
