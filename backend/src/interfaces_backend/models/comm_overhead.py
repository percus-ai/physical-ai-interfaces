from __future__ import annotations

from pydantic import BaseModel, Field


class StatsValue(BaseModel):
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    avg: float = 0.0
    max: float = 0.0


class PointMetrics(BaseModel):
    point_id: str
    sample_count: int = 0
    latency_ms: StatsValue = Field(default_factory=StatsValue)
    jitter_ms: float = 0.0
    drop_rate: float = 0.0
    queue_depth: StatsValue = Field(default_factory=StatsValue)
    payload_bytes: StatsValue = Field(default_factory=StatsValue)


class CommSummaryResponse(BaseModel):
    window_sec: int
    session_id: str | None = None
    arm: str | None = None
    points: list[PointMetrics] = Field(default_factory=list)


class CommEventDigest(BaseModel):
    point_id: str
    timestamp_ns: int
    session_id: str
    trace_id: str
    arm: str
    status: str
    latency_ns: int | None = None
    obs_id: str | None = None
    frame_id: str | None = None
    chunk_id: str | None = None
    queue_depth: int | None = None
    payload_bytes: int | None = None
    drop_count: int | None = None
    tags: dict = Field(default_factory=dict)


class CommPointResponse(BaseModel):
    window_sec: int
    session_id: str | None = None
    arm: str | None = None
    point: PointMetrics
    recent_events: list[CommEventDigest] = Field(default_factory=list)


class CommTraceResponse(BaseModel):
    window_sec: int
    trace_id: str
    events: list[CommEventDigest] = Field(default_factory=list)
