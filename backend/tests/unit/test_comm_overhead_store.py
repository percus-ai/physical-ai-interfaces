from __future__ import annotations

import json
import time

from interfaces_backend.services.comm_overhead_store import CommOverheadStore


def _point(points: list[dict], point_id: str) -> dict:
    for point in points:
        if point["point_id"] == point_id:
            return point
    raise AssertionError(f"point not found: {point_id}")


def test_comm_overhead_store_summary_and_trace(tmp_path) -> None:
    now_ns = time.time_ns()
    lines = [
        {
            "point_id": "CP-01",
            "timestamp_ns": now_ns - 2_000_000,
            "session_id": "session-1",
            "trace_id": "trace-1",
            "arm": "none",
            "status": "ok",
            "latency_ns": 10_000_000,
            "queue_depth": 1,
            "payload_bytes": 100,
            "tags": {},
        },
        {
            "point_id": "CP-01",
            "timestamp_ns": now_ns - 1_000_000,
            "session_id": "session-1",
            "trace_id": "trace-1",
            "arm": "none",
            "status": "ok",
            "latency_ns": 20_000_000,
            "queue_depth": 2,
            "payload_bytes": 200,
            "tags": {},
        },
        {
            "point_id": "CP-01",
            "timestamp_ns": now_ns - 500_000,
            "session_id": "session-1",
            "trace_id": "trace-1",
            "arm": "none",
            "status": "drop",
            "drop_count": 2,
            "latency_ns": 0,
            "queue_depth": 3,
            "payload_bytes": 300,
            "tags": {},
        },
    ]

    path = tmp_path / "comm_events.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=True) + "\n")

    store = CommOverheadStore(file_path=str(path))
    summary = store.get_summary(window_sec=60, session_id="session-1", arm="none")
    cp01 = _point(summary["points"], "CP-01")

    assert cp01["sample_count"] == 3
    assert cp01["latency_ms"]["p50"] == 10.0
    assert cp01["latency_ms"]["p95"] == 20.0
    assert cp01["drop_rate"] == 0.6
    assert cp01["queue_depth"]["max"] == 3.0
    assert cp01["payload_bytes"]["max"] == 300.0

    trace = store.get_trace(trace_id="trace-1", window_sec=60, limit=100)
    assert len(trace["events"]) == 3
    assert trace["events"][0]["point_id"] == "CP-01"
