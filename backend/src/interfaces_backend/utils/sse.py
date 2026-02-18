from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Awaitable, Callable, Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

from percus_ai.observability import ArmId, CommOverheadReporter, PointId, new_trace_id

JsonBuilder = Callable[[], Awaitable[dict]]
_COMM_REPORTER = CommOverheadReporter("backend")


def _format_event(data: str, event: Optional[str]) -> str:
    if event:
        return f"event: {event}\ndata: {data}\n\n"
    return f"data: {data}\n\n"


def sse_response(
    request: Request,
    build_payload: JsonBuilder,
    *,
    interval: float,
    event: Optional[str] = None,
    heartbeat: float = 25.0,
) -> StreamingResponse:
    async def event_stream():
        last_payload: Optional[str] = None
        last_sent = 0.0
        last_sent_ns: Optional[int] = None
        is_operate_status = request.url.path == "/api/stream/operate/status"
        while True:
            if await request.is_disconnected():
                break
            iter_start_ns = time.time_ns()
            payload: dict[str, Any] = {}
            try:
                payload = await build_payload()
                encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            except Exception as exc:  # noqa: BLE001 - surface in stream
                encoded = json.dumps({"error": str(exc)}, ensure_ascii=False)

            now = time.monotonic()
            if encoded != last_payload:
                last_payload = encoded
                last_sent = now
                if is_operate_status:
                    session_id = "stream-operate-status"
                    if isinstance(payload, dict):
                        runner = (((payload.get("inference_runner_status") or {}).get("runner_status")) or {})
                        session_id = str(runner.get("session_id") or session_id)
                    tags: dict[str, Any] = {
                        "event": "sse_message",
                        "path": request.url.path,
                    }
                    now_ns = time.time_ns()
                    if last_sent_ns is not None:
                        tags["interval_ns"] = max(now_ns - last_sent_ns, 0)
                    _COMM_REPORTER.export(
                        point_id=PointId.ST_02,
                        session_id=session_id,
                        trace_id=new_trace_id(),
                        arm=ArmId.NONE,
                        latency_ns=max(now_ns - iter_start_ns, 0),
                        payload_bytes=len(encoded.encode("utf-8")),
                        tags=tags,
                    )
                    last_sent_ns = now_ns
                yield _format_event(encoded, event)
            elif now - last_sent >= heartbeat:
                last_sent = now
                yield ": ping\n\n"

            await asyncio.sleep(interval)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def sse_queue_response(
    request: Request,
    queue: asyncio.Queue[dict[str, Any]],
    *,
    event: Optional[str] = None,
    heartbeat: float = 25.0,
    payload_key: Optional[str] = "payload",
    on_close: Optional[Callable[[], None]] = None,
) -> StreamingResponse:
    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=heartbeat)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue

                if payload_key is None:
                    payload = item
                else:
                    payload = item.get(payload_key)
                    if payload is None:
                        payload = item
                encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                yield _format_event(encoded, event)
        finally:
            if on_close is not None:
                on_close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
