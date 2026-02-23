"""Bridge to VLAbor dashboard websocket control API."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import websockets
from fastapi import HTTPException

_DASHBOARD_WS_URL = os.environ.get("VLABOR_DASHBOARD_WS_URL", "ws://127.0.0.1:8888/ws")


class VlaborDashboardBridge:
    """Websocket client for sending runtime control messages to VLAbor dashboard."""

    def __init__(self, ws_url: str | None = None) -> None:
        self._ws_url = str(ws_url or _DASHBOARD_WS_URL).strip()

    async def set_teleop_enabled(self, *, enabled: bool, timeout_s: float = 3.0) -> dict[str, Any]:
        if not self._ws_url:
            raise HTTPException(status_code=500, detail="VLABOR_DASHBOARD_WS_URL is empty")

        request = {
            "type": "set_teleop_enabled",
            "enabled": bool(enabled),
        }
        deadline = asyncio.get_running_loop().time() + max(float(timeout_s), 0.5)

        try:
            async with websockets.connect(
                self._ws_url,
                open_timeout=min(timeout_s, 5.0),
                ping_interval=20.0,
                ping_timeout=20.0,
            ) as ws:
                await ws.send(json.dumps(request, ensure_ascii=False))
                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise HTTPException(
                            status_code=504,
                            detail="Timed out waiting dashboard teleop response",
                        )
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    payload = self._parse_payload(raw)
                    if payload is None:
                        continue
                    msg_type = str(payload.get("type") or "").strip().lower()
                    if msg_type == "teleop_enabled_response":
                        success = bool(payload.get("success", False))
                        if not success:
                            raise HTTPException(
                                status_code=500,
                                detail=str(payload.get("error") or "Dashboard rejected teleop toggle"),
                            )
                        return payload
                    if msg_type == "error":
                        raise HTTPException(
                            status_code=500,
                            detail=str(payload.get("message") or "Dashboard error"),
                        )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Dashboard websocket unavailable: {exc}",
            ) from exc

    @staticmethod
    def _parse_payload(raw: Any) -> dict[str, Any] | None:
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                return None
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
        return raw if isinstance(raw, dict) else None


_bridge: VlaborDashboardBridge | None = None


def get_vlabor_dashboard_bridge() -> VlaborDashboardBridge:
    global _bridge
    if _bridge is None:
        _bridge = VlaborDashboardBridge()
    return _bridge
