"""HTTP route: POST /v1/tts/synthesize → streaming audio."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .audio_codec import VALID_FORMATS, encode, media_type_for

log = structlog.get_logger().bind(component="synthesizer")

router = APIRouter()


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10_000)
    voice_id: str | None = None
    speed: float = Field(1.0, ge=0.25, le=2.0)
    output_format: str | None = None     # falls back to cfg.output_format_default


@router.post("/v1/tts/synthesize")
async def synthesize(req: SynthesizeRequest, request: Request) -> StreamingResponse:
    state = request.app.state
    backend = state.backend
    cfg = state.cfg

    voice_id = req.voice_id or cfg.default_voice_id or None
    fmt = req.output_format or cfg.output_format_default
    if fmt not in VALID_FORMATS:
        raise HTTPException(status_code=400,
                            detail=f"output_format must be one of {sorted(VALID_FORMATS)}")

    log.info("synthesize_start",
             chars=len(req.text), voice_id=voice_id,
             output_format=fmt, speed=req.speed)

    # Bigger queue + smaller emit chunks → lower first-byte latency. The
    # backend yields one sentence at a time; we re-cut each sentence into
    # ~80 ms slices so the consumer (worker → SIP) starts receiving bytes
    # the moment the first sentence is generated, not when it's done.
    queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=16)
    EMIT_MS = 80

    def _produce() -> None:
        """Run on a thread so we can call sync backend.synthesize in parallel."""
        try:
            slice_samples = max(1, int(backend.sample_rate * EMIT_MS / 1000))
            for pcm_f32 in backend.synthesize(req.text, voice_id, req.speed):
                if pcm_f32.size == 0:
                    continue
                # Slice the sentence into small windows so first-byte arrives
                # as soon as the encoder has anything to send.
                for start in range(0, pcm_f32.size, slice_samples):
                    sub = pcm_f32[start : start + slice_samples]
                    if sub.size == 0:
                        continue
                    wire = encode(sub, backend.sample_rate, fmt)
                    asyncio.run_coroutine_threadsafe(
                        queue.put(wire), loop).result()
        except Exception as exc:                             # pragma: no cover
            log.exception("synthesize_failed", error=str(exc))
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop).result()

    loop = asyncio.get_running_loop()
    producer = loop.run_in_executor(None, _produce)

    async def _stream() -> AsyncIterator[bytes]:
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    return
                yield chunk
        finally:
            producer.cancel()

    return StreamingResponse(
        _stream(),
        media_type=media_type_for(fmt),
        headers={
            # Disable proxy buffering so the first chunk reaches the client
            # the moment we have it.
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-store",
        },
    )
