from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Awaitable, Callable, Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

JsonBuilder = Callable[[], Awaitable[dict]]


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
        while True:
            if await request.is_disconnected():
                break
            try:
                payload = await build_payload()
                encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            except Exception as exc:  # noqa: BLE001 - surface in stream
                encoded = json.dumps({"error": str(exc)}, ensure_ascii=False)

            now = time.monotonic()
            if encoded != last_payload:
                last_payload = encoded
                last_sent = now
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
