"""Base session manager for teleop / recording / inference.

Provides a common lifecycle (create → start → stop → status) with
profile resolution and profile binding persistence.
Subclasses call ``super()`` and add feature-specific logic.
"""

from __future__ import annotations

import threading
from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, ClassVar
from uuid import uuid4

from fastapi import HTTPException

from interfaces_backend.services.vlabor_profiles import (
    VlaborProfileSpec,
    get_active_profile_spec,
    resolve_profile_spec,
    save_session_profile_binding,
)
from percus_ai.db import get_current_user_id

SessionProgressCallback = Callable[[str, float, str, dict[str, Any] | None], None]


def require_user_id() -> str:
    """Return the current user id or raise 401."""
    try:
        return get_current_user_id()
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Login required") from exc


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SessionState:
    """In-memory session state shared across all session kinds."""

    id: str
    kind: str
    status: str = "created"
    profile: VlaborProfileSpec | None = None
    created_at: str = ""
    started_at: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


class BaseSessionManager(ABC):
    """Common lifecycle for all session kinds.

    Subclasses override ``create``, ``start``, ``stop`` and call
    ``super()`` to get the shared behaviour (auth, profile, binding,
    state tracking).
    """

    kind: ClassVar[str]

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.RLock()

    # -- lifecycle ------------------------------------------------------------

    @staticmethod
    def _emit_progress(
        progress_callback: SessionProgressCallback | None,
        *,
        phase: str,
        progress_percent: float,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        if progress_callback is None:
            return
        progress_callback(phase, progress_percent, message, detail)

    async def create(
        self,
        *,
        session_id: str | None = None,
        profile: str | None = None,
        progress_callback: SessionProgressCallback | None = None,
        **kwargs: Any,
    ) -> SessionState:
        """Resolve profile → save binding → track state."""
        require_user_id()
        self._emit_progress(
            progress_callback,
            phase="resolve_profile",
            progress_percent=10.0,
            message="プロファイルを解決しています...",
        )
        resolved = await self._resolve_profile(profile)

        self._emit_progress(
            progress_callback,
            phase="initialize",
            progress_percent=25.0,
            message="セッション情報を初期化しています...",
        )

        self._emit_progress(
            progress_callback,
            phase="persist",
            progress_percent=40.0,
            message="セッション状態を保存しています...",
        )
        resolved_session_id = session_id or self._generate_id()
        state = SessionState(
            id=resolved_session_id,
            kind=self.kind,
            profile=resolved,
            created_at=_utcnow_iso(),
        )
        with self._lock:
            if resolved_session_id in self._sessions:
                raise HTTPException(
                    status_code=409,
                    detail=f"Session already exists: {resolved_session_id}",
                )
            self._sessions[resolved_session_id] = state

        await save_session_profile_binding(
            session_kind=self.kind, session_id=resolved_session_id, profile=resolved
        )
        self._emit_progress(
            progress_callback,
            phase="persist",
            progress_percent=55.0,
            message="セッションバインドを保存しました。",
        )
        return state

    async def start(self, session_id: str, **kwargs: Any) -> SessionState:
        """Transition session to *running*."""
        state = self._get_or_raise(session_id)
        state.status = "running"
        state.started_at = state.started_at or _utcnow_iso()
        return state

    async def stop(self, session_id: str, **kwargs: Any) -> SessionState:
        """Remove session state."""
        with self._lock:
            state = self._sessions.pop(session_id, None)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        state.status = "stopped"
        return state

    def status(self, session_id: str) -> SessionState | None:
        """Return session state (or ``None``)."""
        with self._lock:
            return self._sessions.get(session_id)

    def any_active(self) -> SessionState | None:
        """Return the first active session, if any."""
        with self._lock:
            for state in self._sessions.values():
                if state.status in ("created", "running"):
                    return state
        return None

    # -- helpers --------------------------------------------------------------

    def _get_or_raise(self, session_id: str) -> SessionState:
        with self._lock:
            state = self._sessions.get(session_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        return state

    def _generate_id(self) -> str:
        return uuid4().hex[:16]

    async def _resolve_profile(self, profile: str | None) -> VlaborProfileSpec:
        if profile:
            return resolve_profile_spec(profile)
        return await get_active_profile_spec()
