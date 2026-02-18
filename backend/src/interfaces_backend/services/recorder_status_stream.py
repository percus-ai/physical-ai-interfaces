"""Realtime recorder status bridge (recorder WebSocket -> event bus)."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

import websockets

from interfaces_backend.services.recorder_bridge import RecorderBridge, get_recorder_bridge
from interfaces_backend.services.realtime_events import RealtimeEventBus, get_realtime_event_bus

RECORDING_STATUS_TOPIC = "recording.session_status"

logger = logging.getLogger(__name__)


class RecorderStatusStream:
    """Consumes recorder websocket status and publishes per-session updates."""

    def __init__(
        self,
        recorder: RecorderBridge | None = None,
        bus: RealtimeEventBus | None = None,
    ) -> None:
        self._recorder = recorder or get_recorder_bridge()
        self._bus = bus or get_realtime_event_bus()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._latest_status: dict[str, Any] | None = None
        self._last_active_dataset_id: str | None = None

    def ensure_started(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._thread_entry,
                name="recorder-status-stream",
                daemon=True,
            )
            self._thread.start()

    async def build_session_snapshot(self, session_id: str) -> dict[str, Any]:
        status = self._latest_status_snapshot()
        if status is None:
            try:
                status = await asyncio.to_thread(self._recorder.status)
                if isinstance(status, dict):
                    with self._lock:
                        self._latest_status = dict(status)
            except Exception:
                status = None
        return self._to_session_payload(session_id=session_id, status=status)

    def _thread_entry(self) -> None:
        asyncio.run(self._run_forever())

    async def _run_forever(self) -> None:
        reconnect_delay_s = 1.0
        while True:
            ws_url = self._recorder.websocket_url()
            try:
                async with websockets.connect(
                    ws_url,
                    open_timeout=5.0,
                    ping_interval=20.0,
                    ping_timeout=20.0,
                ) as ws:
                    reconnect_delay_s = 1.0
                    async for message in ws:
                        payload = self._parse_payload(message)
                        if payload is None:
                            continue
                        self._handle_status(payload)
            except Exception as exc:  # noqa: BLE001 - keep reconnecting forever
                logger.warning("Recorder websocket disconnected: %s", exc)
                await asyncio.sleep(reconnect_delay_s)
                reconnect_delay_s = min(reconnect_delay_s * 2.0, 5.0)

    @staticmethod
    def _parse_payload(message: Any) -> dict[str, Any] | None:
        if isinstance(message, bytes):
            try:
                message = message.decode("utf-8")
            except UnicodeDecodeError:
                return None
        if isinstance(message, str):
            try:
                parsed = json.loads(message)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
        return message if isinstance(message, dict) else None

    def _handle_status(self, status: dict[str, Any]) -> None:
        with self._lock:
            self._latest_status = dict(status)
            previous_active = self._last_active_dataset_id
            active_dataset_id = str(status.get("dataset_id") or "").strip() or None
            self._last_active_dataset_id = active_dataset_id

        if active_dataset_id:
            self._bus.publish_threadsafe(
                RECORDING_STATUS_TOPIC,
                active_dataset_id,
                self._to_session_payload(session_id=active_dataset_id, status=status),
            )

        if previous_active and previous_active != active_dataset_id:
            self._bus.publish_threadsafe(
                RECORDING_STATUS_TOPIC,
                previous_active,
                self._to_session_payload(session_id=previous_active, status=status),
            )

    def _latest_status_snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            if self._latest_status is None:
                return None
            return dict(self._latest_status)

    @staticmethod
    def _to_session_payload(session_id: str, status: dict[str, Any] | None) -> dict[str, Any]:
        active_dataset_id = str((status or {}).get("dataset_id") or "").strip()
        if active_dataset_id and active_dataset_id == session_id:
            return {
                "dataset_id": session_id,
                "status": status or {},
            }
        return {
            "dataset_id": session_id,
            "status": {
                "state": "inactive",
                "active_dataset_id": active_dataset_id or None,
            },
        }


_stream: RecorderStatusStream | None = None
_stream_lock = threading.Lock()


def get_recorder_status_stream() -> RecorderStatusStream:
    global _stream
    with _stream_lock:
        if _stream is None:
            _stream = RecorderStatusStream()
    return _stream
