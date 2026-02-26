from __future__ import annotations

import json
import math
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from percus_ai.observability import CommEvent, EventStatus, PointId


_DEFAULT_WINDOW_SEC = 900
_DEFAULT_LIMIT = 500
_DEFAULT_MAX_EVENTS = 200_000


def _extract_otlp_value(value: dict[str, Any]) -> Any:
    if not isinstance(value, dict):
        return None
    if "stringValue" in value:
        return value.get("stringValue")
    if "intValue" in value:
        try:
            return int(value.get("intValue"))
        except Exception:
            return None
    if "doubleValue" in value:
        try:
            return float(value.get("doubleValue"))
        except Exception:
            return None
    if "boolValue" in value:
        return bool(value.get("boolValue"))
    return None


def _extract_attributes(raw_attrs: Any) -> dict[str, Any]:
    if not isinstance(raw_attrs, list):
        return {}
    result: dict[str, Any] = {}
    for item in raw_attrs:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not isinstance(key, str) or not key:
            continue
        value = _extract_otlp_value(item.get("value", {}))
        result[key] = value
    return result


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil((p / 100.0) * len(ordered)) - 1))
    return float(ordered[rank])


def _build_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "avg": 0.0, "max": 0.0}
    return {
        "p50": _percentile(values, 50.0),
        "p95": _percentile(values, 95.0),
        "p99": _percentile(values, 99.0),
        "avg": float(sum(values) / len(values)),
        "max": float(max(values)),
    }


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return float(math.sqrt(var))


class CommOverheadStore:
    def __init__(self, file_path: str | None = None, max_events: int = _DEFAULT_MAX_EVENTS) -> None:
        self._file_path = Path(file_path or os.environ.get("COMM_COLLECTOR_FILE_PATH", "/data/trace/collector/comm_events.jsonl"))
        self._events: deque[CommEvent] = deque(maxlen=max_events)
        self._lock = threading.RLock()
        self._inode: tuple[int, int] | None = None
        self._offset = 0

    def _parse_comm_event_dict(self, data: dict[str, Any]) -> CommEvent | None:
        if "point_id" not in data:
            return None
        try:
            return CommEvent.model_validate(data)
        except Exception:
            return None

    def _parse_otlp_trace(self, data: dict[str, Any]) -> list[CommEvent]:
        resource_spans = data.get("resourceSpans")
        if not isinstance(resource_spans, list):
            return []

        events: list[CommEvent] = []
        for resource_span in resource_spans:
            if not isinstance(resource_span, dict):
                continue
            resource_attrs = _extract_attributes(((resource_span.get("resource") or {}).get("attributes")))

            scope_spans = resource_span.get("scopeSpans")
            if not isinstance(scope_spans, list):
                continue
            for scope_span in scope_spans:
                if not isinstance(scope_span, dict):
                    continue
                spans = scope_span.get("spans")
                if not isinstance(spans, list):
                    continue
                for span in spans:
                    if not isinstance(span, dict):
                        continue
                    attrs = _extract_attributes(span.get("attributes"))
                    point_raw = attrs.get("comm.point_id")
                    if not isinstance(point_raw, str):
                        continue
                    trace_id = attrs.get("comm.trace_id") or span.get("traceId") or "unknown-trace"
                    session_id = attrs.get("comm.session_id") or "unknown-session"

                    tags: dict[str, Any] = {}
                    for key, value in attrs.items():
                        if key.startswith("comm.tag."):
                            tags[key.replace("comm.tag.", "", 1)] = value
                    if "service.name" in resource_attrs and "service" not in tags:
                        tags["service"] = resource_attrs.get("service.name")

                    start_ns = attrs.get("comm.timestamp_ns") or span.get("startTimeUnixNano")
                    end_ns = span.get("endTimeUnixNano")
                    latency_ns = attrs.get("comm.latency_ns")
                    if latency_ns is None and start_ns is not None and end_ns is not None:
                        try:
                            latency_ns = max(int(end_ns) - int(start_ns), 0)
                        except Exception:
                            latency_ns = None

                    raw_payload = {
                        "point_id": point_raw,
                        "timestamp_ns": _to_int(start_ns) or time.time_ns(),
                        "session_id": str(session_id),
                        "trace_id": str(trace_id),
                        "arm": str(attrs.get("comm.arm") or "none"),
                        "status": str(attrs.get("comm.status") or "ok"),
                        "latency_ns": _to_int(latency_ns),
                        "obs_id": attrs.get("comm.obs_id"),
                        "frame_id": attrs.get("comm.frame_id"),
                        "chunk_id": attrs.get("comm.chunk_id"),
                        "queue_depth": _to_int(attrs.get("comm.queue_depth")),
                        "payload_bytes": _to_int(attrs.get("comm.payload_bytes")),
                        "drop_count": _to_int(attrs.get("comm.drop_count")),
                        "tags": tags,
                    }
                    event = self._parse_comm_event_dict(raw_payload)
                    if event is not None:
                        events.append(event)
        return events

    def _parse_line(self, line: str) -> list[CommEvent]:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return []

        if not isinstance(data, dict):
            return []

        direct = self._parse_comm_event_dict(data)
        if direct is not None:
            return [direct]

        return self._parse_otlp_trace(data)

    def refresh(self) -> None:
        with self._lock:
            path = self._file_path
            if not path.exists():
                return

            stat = path.stat()
            inode = (stat.st_dev, stat.st_ino)
            if self._inode is None:
                self._inode = inode
            elif self._inode != inode or stat.st_size < self._offset:
                self._inode = inode
                self._offset = 0

            with path.open("r", encoding="utf-8") as handle:
                handle.seek(self._offset)
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    events = self._parse_line(line)
                    for event in events:
                        self._events.append(event)
                self._offset = handle.tell()

    def _filtered_events(
        self,
        *,
        window_sec: int,
        session_id: str | None = None,
        arm: str | None = None,
        point_id: PointId | None = None,
        trace_id: str | None = None,
    ) -> list[CommEvent]:
        now = time.time_ns()
        threshold = now - int(window_sec * 1_000_000_000)
        with self._lock:
            events = list(self._events)

        filtered: list[CommEvent] = []
        for event in events:
            if event.timestamp_ns < threshold:
                continue
            if session_id and event.session_id != session_id:
                continue
            if arm and event.arm.value != arm:
                continue
            if point_id and event.point_id != point_id:
                continue
            if trace_id and event.trace_id != trace_id:
                continue
            filtered.append(event)
        return filtered

    def _aggregate_point(self, point_id: str, events: list[CommEvent]) -> dict[str, Any]:
        latency_values = [float(e.latency_ns) / 1_000_000.0 for e in events if e.status == EventStatus.OK and e.latency_ns is not None]
        queue_values = [float(e.queue_depth) for e in events if e.queue_depth is not None]
        payload_values = [float(e.payload_bytes) for e in events if e.payload_bytes is not None]

        drop_events = sum(1 for e in events if e.status == EventStatus.DROP)
        drop_count_total = sum(int(e.drop_count or 0) for e in events)
        drop_denominator = len(events) + drop_count_total
        drop_rate = 0.0 if drop_denominator <= 0 else float((drop_events + drop_count_total) / drop_denominator)

        return {
            "point_id": point_id,
            "sample_count": len(events),
            "latency_ms": _build_stats(latency_values),
            "jitter_ms": _stddev(latency_values),
            "drop_rate": drop_rate,
            "queue_depth": _build_stats(queue_values),
            "payload_bytes": _build_stats(payload_values),
        }

    def get_summary(self, *, window_sec: int = _DEFAULT_WINDOW_SEC, session_id: str | None = None, arm: str | None = None) -> dict[str, Any]:
        self.refresh()
        events = self._filtered_events(window_sec=window_sec, session_id=session_id, arm=arm)

        grouped: dict[str, list[CommEvent]] = defaultdict(list)
        for event in events:
            grouped[event.point_id.value].append(event)

        points: list[dict[str, Any]] = []
        for point_id in PointId:
            points.append(self._aggregate_point(point_id.value, grouped.get(point_id.value, [])))

        return {
            "window_sec": int(window_sec),
            "session_id": session_id,
            "arm": arm,
            "points": points,
        }

    def get_point(
        self,
        *,
        point_id: PointId,
        window_sec: int = _DEFAULT_WINDOW_SEC,
        session_id: str | None = None,
        arm: str | None = None,
        recent_limit: int = 50,
    ) -> dict[str, Any]:
        self.refresh()
        events = self._filtered_events(window_sec=window_sec, session_id=session_id, arm=arm, point_id=point_id)
        events_sorted = sorted(events, key=lambda e: e.timestamp_ns, reverse=True)

        return {
            "window_sec": int(window_sec),
            "session_id": session_id,
            "arm": arm,
            "point": self._aggregate_point(point_id.value, events),
            "recent_events": [event.model_dump(mode="json") for event in events_sorted[:recent_limit]],
        }

    def get_trace(self, *, trace_id: str, window_sec: int = _DEFAULT_WINDOW_SEC, limit: int = _DEFAULT_LIMIT) -> dict[str, Any]:
        self.refresh()
        events = self._filtered_events(window_sec=window_sec, trace_id=trace_id)
        events_sorted = sorted(events, key=lambda e: e.timestamp_ns)
        if limit > 0:
            events_sorted = events_sorted[:limit]

        return {
            "window_sec": int(window_sec),
            "trace_id": trace_id,
            "events": [event.model_dump(mode="json") for event in events_sorted],
        }


_store: CommOverheadStore | None = None
_store_lock = threading.Lock()


def get_comm_overhead_store() -> CommOverheadStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = CommOverheadStore()
    return _store
