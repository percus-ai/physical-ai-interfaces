"""In-process realtime event bus for SSE streams."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


Channel = tuple[str, str]


@dataclass
class RealtimeSubscription:
    topic: str
    key: str
    queue: asyncio.Queue[dict[str, Any]]
    _bus: "RealtimeEventBus"
    _subscriber_id: str
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._bus.unsubscribe(self.topic, self.key, self._subscriber_id)


class RealtimeEventBus:
    """Simple latest-state event bus with per-channel subscriptions."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._latest: dict[Channel, dict[str, Any]] = {}
        self._subscribers: dict[Channel, dict[str, asyncio.Queue[dict[str, Any]]]] = {}
        self._seq = 0

    def subscribe(self, topic: str, key: str, *, max_queue_size: int = 32) -> RealtimeSubscription:
        loop = asyncio.get_running_loop()
        channel = (topic, key)
        subscriber_id = uuid4().hex
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_queue_size)
        latest: dict[str, Any] | None = None
        with self._lock:
            self._loop = loop
            bucket = self._subscribers.setdefault(channel, {})
            bucket[subscriber_id] = queue
            latest = self._latest.get(channel)
        if latest is not None:
            self._queue_put_latest(queue, latest)
        return RealtimeSubscription(
            topic=topic,
            key=key,
            queue=queue,
            _bus=self,
            _subscriber_id=subscriber_id,
        )

    def unsubscribe(self, topic: str, key: str, subscriber_id: str) -> None:
        channel = (topic, key)
        with self._lock:
            bucket = self._subscribers.get(channel)
            if not bucket:
                return
            bucket.pop(subscriber_id, None)
            if not bucket:
                self._subscribers.pop(channel, None)

    def subscriber_count(self, topic: str, key: str) -> int:
        channel = (topic, key)
        with self._lock:
            bucket = self._subscribers.get(channel)
            if not bucket:
                return 0
            return len(bucket)

    async def publish(self, topic: str, key: str, payload: dict[str, Any]) -> None:
        """Publish from event-loop context."""
        event = self._build_event(topic=topic, key=key, payload=payload)
        queues = self._store_and_get_queues(topic=topic, key=key, event=event)
        for queue in queues:
            self._queue_put_latest(queue, event)

    def publish_threadsafe(self, topic: str, key: str, payload: dict[str, Any]) -> None:
        """Publish safely from any thread."""
        event = self._build_event(topic=topic, key=key, payload=payload)
        queues = self._store_and_get_queues(topic=topic, key=key, event=event)
        with self._lock:
            loop = self._loop
        if loop is None or not loop.is_running() or not queues:
            return

        def dispatch() -> None:
            for queue in queues:
                self._queue_put_latest(queue, event)

        loop.call_soon_threadsafe(dispatch)

    def _store_and_get_queues(
        self,
        *,
        topic: str,
        key: str,
        event: dict[str, Any],
    ) -> list[asyncio.Queue[dict[str, Any]]]:
        channel = (topic, key)
        with self._lock:
            self._latest[channel] = event
            bucket = self._subscribers.get(channel) or {}
            return list(bucket.values())

    def _build_event(self, *, topic: str, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._seq += 1
            seq = self._seq
        return {
            "topic": topic,
            "key": key,
            "seq": seq,
            "ts": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }

    @staticmethod
    def _queue_put_latest(queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            # Rare race; drop event for this subscriber.
            return


_event_bus: RealtimeEventBus | None = None
_event_bus_lock = threading.Lock()


def get_realtime_event_bus() -> RealtimeEventBus:
    global _event_bus
    with _event_bus_lock:
        if _event_bus is None:
            _event_bus = RealtimeEventBus()
    return _event_bus
