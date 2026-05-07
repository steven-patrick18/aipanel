"""Streaming WebSocket: VAD-segmented transcription with partials.

Wire protocol
-------------

Client → Server::

    {"type":"start","language":"en","sample_rate":16000,"hint_words":["..."]}
    <binary frame>   # raw PCM, 16 kHz, signed 16-bit little-endian, ~100 ms
    <binary frame>
    ...
    {"type":"end"}

Server → Client::

    {"type":"partial","text":"hello how","stability":0.7}
    {"type":"final","text":"hello how are you","duration_ms":1820}
    {"type":"error","message":"..."}

Implementation notes
--------------------

* silero-vad is fed in fixed 512-sample chunks at 16 kHz (~32 ms native).
  We accumulate incoming bytes in a buffer and pop chunks of that exact
  size; leftover bytes wait for the next inbound frame.
* During an active speech segment we run faster-whisper at most every
  ``partial_interval_ms`` over the segment-so-far with ``beam_size=1``.
  Stability is a heuristic: 0.5 if the partial differs from the prior one,
  rising toward 0.9 as it stabilises.
* On VAD-detected end-of-speech (or 30 s max-segment cap) we run a final
  pass with ``beam_size=cfg.beam_size`` and emit ``type=final``.
* Heavy work (whisper transcribe) runs in a thread executor so the WS event
  loop keeps reading inbound frames.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

import numpy as np
import structlog
import torch
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .config import STTConfig
from .model_loader import get_models

log = structlog.get_logger().bind(component="streaming")

router = APIRouter()

VAD_CHUNK_SAMPLES = 512                 # silero-vad native @ 16 kHz
BYTES_PER_SAMPLE = 2                    # s16le
VAD_CHUNK_BYTES = VAD_CHUNK_SAMPLES * BYTES_PER_SAMPLE
SAMPLE_RATE = 16000


@dataclass
class _StreamState:
    cfg: STTConfig
    language: str
    pending_bytes: bytearray = field(default_factory=bytearray)
    speech_buffer: list[np.ndarray] = field(default_factory=list)
    speech_started_at: float | None = None
    last_partial_at: float = 0.0
    last_partial_text: str = ""
    partial_repeat_count: int = 0
    vad_iter: object = None             # silero VADIterator instance
    finalize_pending: bool = False

    @property
    def speech_active(self) -> bool:
        return self.speech_started_at is not None

    def speech_samples(self) -> np.ndarray:
        if not self.speech_buffer:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self.speech_buffer)


def _bytes_to_f32(buf: bytes) -> np.ndarray:
    """s16le → float32 in [-1, 1]."""
    return np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0


def _stability(prev: str, current: str, repeat_count: int) -> float:
    if not current:
        return 0.0
    if current == prev:
        # The longer it stays the same, the more we trust it.
        return min(0.5 + 0.1 * repeat_count, 0.9)
    if prev and current.startswith(prev):
        return 0.7
    return 0.4


@router.websocket("/v1/stt/stream")
async def stream(ws: WebSocket) -> None:
    await ws.accept()

    models = get_models()
    if models is None:
        await ws.send_text(json.dumps({"type": "error",
                                       "message": "model not loaded"}))
        await ws.close(code=1011)
        return

    # Default config — overwritten by the start message.
    from .config import load_config
    cfg = load_config()
    state = _StreamState(cfg=cfg, language=cfg.language)
    state.vad_iter = models.vad_iterator_factory()

    log.info("ws_open", peer=str(ws.client))

    try:
        while True:
            try:
                msg = await ws.receive()
            except WebSocketDisconnect:
                log.info("ws_disconnect", peer=str(ws.client))
                break

            if msg.get("type") == "websocket.disconnect":
                break

            text = msg.get("text")
            data = msg.get("bytes")

            if text is not None:
                ctrl = await _handle_control(ws, state, text)
                if ctrl == "end":
                    await _finalize(ws, state, models)
                    break
            elif data is not None:
                await _handle_audio(ws, state, models, data)
    except Exception:
        log.exception("ws_handler_crashed")
        try:
            await ws.send_text(json.dumps({"type": "error",
                                           "message": "internal error"}))
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except RuntimeError:
            pass


# ---------------------------------------------------------------------------
# Control / audio handlers
# ---------------------------------------------------------------------------

async def _handle_control(ws: WebSocket, state: _StreamState, text: str) -> str:
    """Returns 'end' if we should finalize and close; '' otherwise."""
    try:
        ctrl = json.loads(text)
    except json.JSONDecodeError:
        await ws.send_text(json.dumps({"type": "error",
                                       "message": "invalid json"}))
        return ""
    kind = ctrl.get("type")
    if kind == "start":
        state.language = ctrl.get("language") or state.cfg.language
        sr = int(ctrl.get("sample_rate") or SAMPLE_RATE)
        if sr != SAMPLE_RATE:
            await ws.send_text(json.dumps({
                "type": "error",
                "message": f"sample_rate must be {SAMPLE_RATE} (got {sr})",
            }))
        log.info("stream_start",
                 language=state.language,
                 hint_words=ctrl.get("hint_words"))
    elif kind == "end":
        return "end"
    else:
        log.warning("ws_unknown_control", kind=kind)
    return ""


async def _handle_audio(
    ws: WebSocket,
    state: _StreamState,
    models,
    chunk: bytes,
) -> None:
    """Buffer + VAD + maybe partial."""
    state.pending_bytes.extend(chunk)

    # Drain whole VAD chunks out of pending_bytes.
    while len(state.pending_bytes) >= VAD_CHUNK_BYTES:
        block = bytes(state.pending_bytes[:VAD_CHUNK_BYTES])
        del state.pending_bytes[:VAD_CHUNK_BYTES]

        f32 = _bytes_to_f32(block)
        # silero expects a torch.Tensor.
        tensor = torch.from_numpy(f32)

        try:
            vad_evt = state.vad_iter(tensor, return_seconds=False)
        except Exception:                                    # pragma: no cover
            vad_evt = None

        if state.speech_active or vad_evt:
            state.speech_buffer.append(f32)

        if vad_evt:
            if "start" in vad_evt and not state.speech_active:
                state.speech_started_at = time.monotonic()
                state.last_partial_text = ""
                state.partial_repeat_count = 0
                log.debug("vad_speech_start")
            if "end" in vad_evt and state.speech_active:
                log.debug("vad_speech_end")
                await _emit_final(ws, state, models)
                _reset_segment(state)

        # Hard cap on segment length to bound latency.
        if state.speech_active:
            elapsed = time.monotonic() - (state.speech_started_at or 0.0)
            if elapsed >= state.cfg.max_segment_sec:
                log.info("vad_segment_cap", elapsed_sec=elapsed)
                await _emit_final(ws, state, models)
                _reset_segment(state)
                continue

        # Periodic partial.
        now = time.monotonic()
        if (
            state.speech_active
            and (now - state.last_partial_at) * 1000.0 >= state.cfg.partial_interval_ms
        ):
            state.last_partial_at = now
            await _emit_partial(ws, state, models)


def _reset_segment(state: _StreamState) -> None:
    state.speech_buffer.clear()
    state.speech_started_at = None
    state.last_partial_at = 0.0
    state.last_partial_text = ""
    state.partial_repeat_count = 0


# ---------------------------------------------------------------------------
# Whisper invocations (offloaded to thread executor)
# ---------------------------------------------------------------------------

def _run_whisper(models, pcm: np.ndarray, language: str, beam: int) -> str:
    """Faster-whisper transcribe. ``language="auto"`` (or empty/falsy) lets
    whisper auto-detect — this is what enables true multilingual support
    without a per-call language hint. The model used (``large-v3`` by
    default) covers 99 languages out of the box."""
    lang_arg: str | None = None if (not language or language == "auto") else language
    segs, _ = models.whisper.transcribe(
        pcm,
        language=lang_arg,
        beam_size=beam,
        vad_filter=False,
    )
    return "".join(s.text for s in segs).strip()


async def _emit_partial(ws: WebSocket, state: _StreamState, models) -> None:
    pcm = state.speech_samples()
    if pcm.size < SAMPLE_RATE // 4:    # < 250 ms of audio — too short
        return
    text = await asyncio.to_thread(
        _run_whisper, models, pcm, state.language, state.cfg.beam_size_partial
    )
    if text == state.last_partial_text:
        state.partial_repeat_count += 1
    else:
        state.partial_repeat_count = 0
    stability = _stability(state.last_partial_text, text,
                           state.partial_repeat_count)
    state.last_partial_text = text
    try:
        await ws.send_text(json.dumps({
            "type": "partial",
            "text": text,
            "stability": round(stability, 2),
        }))
    except RuntimeError:
        pass


async def _emit_final(ws: WebSocket, state: _StreamState, models) -> None:
    pcm = state.speech_samples()
    if pcm.size == 0:
        return
    text = await asyncio.to_thread(
        _run_whisper, models, pcm, state.language, state.cfg.beam_size
    )
    duration_ms = int(round(pcm.size / 16.0))
    try:
        await ws.send_text(json.dumps({
            "type": "final",
            "text": text,
            "duration_ms": duration_ms,
        }))
    except RuntimeError:
        pass
    log.info("emit_final", chars=len(text), duration_ms=duration_ms)


async def _finalize(ws: WebSocket, state: _StreamState, models) -> None:
    """Called on explicit {"type":"end"} from the client."""
    if state.speech_active and state.speech_buffer:
        await _emit_final(ws, state, models)
