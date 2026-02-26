from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import pytest
from fastapi import HTTPException


def _load_analytics_module():
    repo_root = Path(__file__).resolve().parents[4]
    analytics_path = repo_root / "interfaces" / "backend" / "src" / "interfaces_backend" / "api" / "analytics.py"
    spec = importlib.util.spec_from_file_location("interfaces_backend_api_analytics_test", analytics_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load analytics module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


analytics = _load_analytics_module()


class _DummyStore:
    def get_summary(self, *, window_sec: int, session_id: str | None, arm: str | None):
        return {
            "window_sec": window_sec,
            "session_id": session_id,
            "arm": arm,
            "points": [],
        }

    def get_point(self, *, point_id, window_sec: int, session_id: str | None, arm: str | None):
        return {
            "window_sec": window_sec,
            "session_id": session_id,
            "arm": arm,
            "point": {
                "point_id": point_id.value,
                "sample_count": 0,
                "latency_ms": {"p50": 0.0, "p95": 0.0, "p99": 0.0, "avg": 0.0, "max": 0.0},
                "jitter_ms": 0.0,
                "drop_rate": 0.0,
                "queue_depth": {"p50": 0.0, "p95": 0.0, "p99": 0.0, "avg": 0.0, "max": 0.0},
                "payload_bytes": {"p50": 0.0, "p95": 0.0, "p99": 0.0, "avg": 0.0, "max": 0.0},
            },
            "recent_events": [],
        }

    def get_trace(self, *, trace_id: str, window_sec: int, limit: int):
        return {
            "window_sec": window_sec,
            "trace_id": trace_id,
            "events": [],
        }


def test_comm_overhead_summary_uses_store(monkeypatch):
    monkeypatch.setattr(analytics, "get_comm_overhead_store", lambda: _DummyStore())
    response = asyncio.run(
        analytics.get_comm_overhead_summary(window_sec=123, session_id="s1", arm="left")
    )
    assert response.window_sec == 123
    assert response.session_id == "s1"
    assert response.arm == "left"


def test_comm_overhead_point_rejects_invalid_point(monkeypatch):
    monkeypatch.setattr(analytics, "get_comm_overhead_store", lambda: _DummyStore())
    with pytest.raises(HTTPException):
        asyncio.run(analytics.get_comm_overhead_point(point_id="INVALID", window_sec=60))
