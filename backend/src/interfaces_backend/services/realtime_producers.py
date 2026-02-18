"""Realtime producer hub for shared SSE channels."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from interfaces_backend.services.realtime_events import RealtimeEventBus, get_realtime_event_bus

ProducerBuilder = Callable[[], Awaitable[dict[str, Any]]]

logger = logging.getLogger(__name__)


@dataclass
class _ProducerEntry:
    task: asyncio.Task[None]


class RealtimeProducerHub:
    """Runs one shared producer task per SSE channel."""

    def __init__(self, bus: RealtimeEventBus | None = None) -> None:
        self._bus = bus or get_realtime_event_bus()
        self._lock = threading.RLock()
        self._producers: dict[tuple[str, str], _ProducerEntry] = {}

    def ensure_polling(
        self,
        *,
        topic: str,
        key: str,
        build_payload: ProducerBuilder,
        interval: float,
        idle_ttl: float = 30.0,
    ) -> None:
        channel = (topic, key)
        with self._lock:
            entry = self._producers.get(channel)
            if entry is not None and not entry.task.done():
                return
            task = asyncio.create_task(
                self._run_polling_loop(
                    topic=topic,
                    key=key,
                    build_payload=build_payload,
                    interval=max(float(interval), 0.05),
                    idle_ttl=max(float(idle_ttl), 1.0),
                )
            )
            self._producers[channel] = _ProducerEntry(task=task)

    async def publish_once(
        self,
        *,
        topic: str,
        key: str,
        build_payload: ProducerBuilder,
    ) -> None:
        payload = await self._safe_build_payload(topic=topic, key=key, build_payload=build_payload)
        await self._bus.publish(topic, key, payload)

    async def _run_polling_loop(
        self,
        *,
        topic: str,
        key: str,
        build_payload: ProducerBuilder,
        interval: float,
        idle_ttl: float,
    ) -> None:
        channel = (topic, key)
        last_payload_encoded: str | None = None
        idle_started_at: float | None = None
        try:
            while True:
                payload = await self._safe_build_payload(
                    topic=topic,
                    key=key,
                    build_payload=build_payload,
                )
                encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                if encoded != last_payload_encoded:
                    last_payload_encoded = encoded
                    await self._bus.publish(topic, key, payload)

                if self._bus.subscriber_count(topic, key) > 0:
                    idle_started_at = None
                else:
                    if idle_started_at is None:
                        idle_started_at = time.monotonic()
                    elif time.monotonic() - idle_started_at >= idle_ttl:
                        return

                await asyncio.sleep(interval)
        finally:
            with self._lock:
                current = self._producers.get(channel)
                if current is not None and current.task is asyncio.current_task():
                    self._producers.pop(channel, None)

    async def _safe_build_payload(
        self,
        *,
        topic: str,
        key: str,
        build_payload: ProducerBuilder,
    ) -> dict[str, Any]:
        try:
            payload = await build_payload()
            if isinstance(payload, dict):
                return payload
            return {"error": f"Invalid payload type: {type(payload).__name__}"}
        except Exception as exc:  # noqa: BLE001 - surfaced as stream payload
            logger.exception("Realtime producer error: topic=%s key=%s", topic, key)
            return {"error": str(exc)}


_producer_hub: RealtimeProducerHub | None = None
_producer_hub_lock = threading.Lock()


def get_realtime_producer_hub() -> RealtimeProducerHub:
    global _producer_hub
    with _producer_hub_lock:
        if _producer_hub is None:
            _producer_hub = RealtimeProducerHub()
    return _producer_hub
