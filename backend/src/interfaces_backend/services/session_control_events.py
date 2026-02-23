"""Session control event helpers for backend SSE channels."""

from __future__ import annotations

import logging
from typing import Any

from interfaces_backend.services.realtime_events import get_realtime_event_bus

SESSION_CONTROL_TOPIC = "session.control"
_VALID_SESSION_KINDS = {"recording", "inference", "teleop", "operate"}

logger = logging.getLogger(__name__)


def normalize_session_kind(session_kind: str) -> str:
    normalized = str(session_kind or "").strip().lower()
    if normalized not in _VALID_SESSION_KINDS:
        raise ValueError(f"Unsupported session_kind: {session_kind}")
    return normalized


def session_control_channel_key(*, session_kind: str, session_id: str | None) -> str:
    normalized_kind = normalize_session_kind(session_kind)
    normalized_session_id = str(session_id or "").strip() or "global"
    return f"{normalized_kind}:{normalized_session_id}"


async def publish_session_control_event(
    *,
    session_kind: str,
    action: str,
    phase: str,
    session_id: str | None = None,
    operation_id: str | None = None,
    success: bool | None = None,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "session_kind": normalize_session_kind(session_kind),
        "session_id": str(session_id or "").strip() or None,
        "action": str(action or "").strip(),
        "phase": str(phase or "").strip(),
    }
    if operation_id is not None:
        payload["operation_id"] = str(operation_id).strip() or None
    if success is not None:
        payload["success"] = bool(success)
    if message:
        payload["message"] = message
    if details:
        payload["details"] = details

    bus = get_realtime_event_bus()
    await bus.publish(
        SESSION_CONTROL_TOPIC,
        session_control_channel_key(session_kind=session_kind, session_id=session_id),
        payload,
    )


async def publish_session_control_event_safely(
    *,
    session_kind: str,
    action: str,
    phase: str,
    session_id: str | None = None,
    operation_id: str | None = None,
    success: bool | None = None,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    try:
        await publish_session_control_event(
            session_kind=session_kind,
            action=action,
            phase=phase,
            session_id=session_id,
            operation_id=operation_id,
            success=success,
            message=message,
            details=details,
        )
    except Exception as exc:  # noqa: BLE001 - event emission must not break API paths
        logger.warning("Failed to publish session control event: %s", exc)
