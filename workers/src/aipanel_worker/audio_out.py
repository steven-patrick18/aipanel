"""Audio outbound: TTS HTTP stream → SIP audio_out frames.

The TTS server returns raw bytes in the requested format. We always ask for
``pcm_s16le_8000`` so we can chunk into 320-byte (20 ms) frames and write
them to the SIP socket as ``FRAME_AUDIO_OUT``.

Cancellation
------------

When the conversation layer signals barge-in (or a tool result wants to
interrupt the current utterance), it sets ``cancel_event``. The TTS HTTP
stream is closed, the leftover queued frames are discarded, and the loop
returns to waiting for the next item on ``speech_queue``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx
import structlog

from .metrics import M_AUDIO_DROPS, M_TTS_FIRST_BYTE
from .sip_protocol import PCM_FRAME_BYTES

log = structlog.get_logger().bind(component="audio_out")


@dataclass
class SpeechRequest:
    """One unit of speech to render. Either ``text`` or pre-rendered ``audio``
    (used for backchannels — currently unused, see humanize.py)."""
    text: str = ""
    audio: bytes = b""
    voice_id: str | None = None
    is_terminal: bool = False
    """If True, signals end-of-call after playback completes."""
    request_id: str = ""


class AudioOutPipeline:
    """Drains ``speech_queue`` → TTS → ``frames_out_queue`` (bytes per frame)."""

    def __init__(
        self,
        tts_url: str,
        voice_id_default: str,
        speech_queue: asyncio.Queue[SpeechRequest | None],
        frames_out_queue: asyncio.Queue[bytes],
        cancel_event: asyncio.Event,
        on_speech_started=None,
        on_speech_finished=None,
    ) -> None:
        self.tts_url = tts_url.rstrip("/")
        self.voice_id_default = voice_id_default
        self.speech_queue = speech_queue
        self.frames_out_queue = frames_out_queue
        self.cancel_event = cancel_event
        self._on_started = on_speech_started or (lambda req: None)
        self._on_finished = on_speech_finished or (lambda req, was_cancelled: None)

        self._client: httpx.AsyncClient | None = None
        self._stop = asyncio.Event()

    async def __aenter__(self) -> "AudioOutPipeline":
        # http2=True lets us reuse the connection across sentences cheaply.
        self._client = httpx.AsyncClient(
            base_url=self.tts_url,
            timeout=httpx.Timeout(60.0, connect=5.0),
            http2=True,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def stop(self) -> None:
        self._stop.set()
        await self.speech_queue.put(None)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                req = await self.speech_queue.get()
            except asyncio.CancelledError:
                return
            if req is None:
                return

            self.cancel_event.clear()
            self._on_started(req)
            cancelled = False
            try:
                if req.audio:
                    await self._enqueue_audio_bytes(req.audio)
                else:
                    cancelled = await self._stream_tts(req)
            except asyncio.CancelledError:
                cancelled = True
                raise
            except Exception as exc:
                log.exception("audio_out_failed",
                              error=str(exc), request_id=req.request_id)
            finally:
                self._on_finished(req, cancelled)

    # ------------------------------------------------------------------
    # TTS streaming
    # ------------------------------------------------------------------

    async def _stream_tts(self, req: SpeechRequest) -> bool:
        """Returns True if cancelled mid-stream, False otherwise."""
        body = {
            "text": req.text,
            "voice_id": req.voice_id or self.voice_id_default or None,
            "output_format": "pcm_s16le_8000",
            "speed": 1.0,
        }
        started = time.monotonic()
        first_byte = False
        leftover = bytearray()
        cancelled = False

        try:
            async with self._client.stream(
                "POST", "/v1/tts/synthesize", json=body
            ) as resp:
                if resp.status_code != 200:
                    log.warning("tts_http_error",
                                status=resp.status_code,
                                request_id=req.request_id)
                    return False
                async for chunk in resp.aiter_bytes():
                    if self.cancel_event.is_set() or self._stop.is_set():
                        cancelled = True
                        break
                    if not first_byte:
                        first_byte = True
                        M_TTS_FIRST_BYTE.observe(time.monotonic() - started)
                    leftover.extend(chunk)
                    while len(leftover) >= PCM_FRAME_BYTES:
                        frame = bytes(leftover[:PCM_FRAME_BYTES])
                        del leftover[:PCM_FRAME_BYTES]
                        await self._enqueue_frame(frame)
        except (httpx.HTTPError, asyncio.CancelledError) as exc:
            log.warning("tts_stream_failed",
                        error=str(exc), request_id=req.request_id)
            return cancelled

        # Pad-out and emit any trailing bytes so we don't drop a half-frame.
        if leftover and not cancelled:
            pad = bytes(PCM_FRAME_BYTES - len(leftover))
            await self._enqueue_frame(bytes(leftover) + pad)

        return cancelled

    async def _enqueue_audio_bytes(self, pcm: bytes) -> None:
        for i in range(0, len(pcm), PCM_FRAME_BYTES):
            chunk = pcm[i:i + PCM_FRAME_BYTES]
            if len(chunk) < PCM_FRAME_BYTES:
                chunk = chunk + bytes(PCM_FRAME_BYTES - len(chunk))
            if self.cancel_event.is_set() or self._stop.is_set():
                return
            await self._enqueue_frame(chunk)

    async def _enqueue_frame(self, frame: bytes) -> None:
        try:
            self.frames_out_queue.put_nowait(frame)
        except asyncio.QueueFull:
            # Drop oldest to keep the playout queue bounded — a stuck SIP
            # writer would otherwise let TTS produce unboundedly.
            try:
                self.frames_out_queue.get_nowait()
                M_AUDIO_DROPS.labels(direction="out").inc()
            except asyncio.QueueEmpty:                       # pragma: no cover
                pass
            self.frames_out_queue.put_nowait(frame)
