"""Hand-rolled Server-Sent Events helpers.

We avoid the ``sse-starlette`` dep — text/event-stream is simple enough
that 30 lines does the job. Each event is one JSON object on a single
``data:`` line.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import Request
from fastapi.responses import StreamingResponse

KEEPALIVE_INTERVAL_SEC = 15.0


async def _format_loop(
    request: Request,
    source: AsyncIterator[dict],
) -> AsyncIterator[bytes]:
    """Wraps a JSON-event source as ``data: {...}\\n\\n`` and emits keepalives."""
    keepalive_at = asyncio.get_event_loop().time() + KEEPALIVE_INTERVAL_SEC

    # Initial comment so EventSource opens the connection promptly.
    yield b": connected\n\n"

    async def _next_event() -> dict | None:
        try:
            return await asyncio.wait_for(
                source.__anext__(), timeout=KEEPALIVE_INTERVAL_SEC,
            )
        except (asyncio.TimeoutError, StopAsyncIteration):
            return None

    while True:
        if await request.is_disconnected():
            return
        evt = await _next_event()
        now = asyncio.get_event_loop().time()
        if evt is None:
            if now >= keepalive_at:
                yield b": keepalive\n\n"
                keepalive_at = now + KEEPALIVE_INTERVAL_SEC
            continue
        yield f"data: {json.dumps(evt)}\n\n".encode("utf-8")
        keepalive_at = now + KEEPALIVE_INTERVAL_SEC


def sse_response(
    request: Request,
    source: AsyncIterator[dict],
) -> StreamingResponse:
    return StreamingResponse(
        _format_loop(request, source),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",     # disable nginx buffering for SSE
            "Connection": "keep-alive",
        },
    )
