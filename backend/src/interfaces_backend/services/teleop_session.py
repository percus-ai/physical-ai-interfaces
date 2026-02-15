"""Teleop session manager."""

from __future__ import annotations

import threading
from typing import Any

from interfaces_backend.services.session_manager import BaseSessionManager, SessionState

_SESSION_ID = "teleop"


class TeleopSessionManager(BaseSessionManager):
    kind = "teleop"

    def _generate_id(self) -> str:
        return _SESSION_ID

    async def create(self, *, profile: str | None = None, **kwargs: Any) -> SessionState:
        # If already running, return existing session
        existing = self.status(_SESSION_ID)
        if existing and existing.status == "running":
            return existing

        state = await super().create(profile=profile, **kwargs)
        state.extras["domain_id"] = kwargs.get("domain_id")
        state.extras["dev_mode"] = bool(kwargs.get("dev_mode", False))
        return state


# -- singleton ----------------------------------------------------------------

_manager: TeleopSessionManager | None = None
_lock = threading.Lock()


def get_teleop_session_manager() -> TeleopSessionManager:
    global _manager
    with _lock:
        if _manager is None:
            _manager = TeleopSessionManager()
    return _manager
