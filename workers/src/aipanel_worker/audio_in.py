"""Audio inbound: SIP audio_in frames → resample → STT WebSocket.

Protocol notes
--------------

* SIP frames arrive at 8 kHz s16le, 320 bytes / 20 ms.
* STT expects 16 kHz s16le; we use ``audioop.ratecv`` for a stateful 8→16k
  upsample (linear interpolation) — quality is fine for telephony.
* The STT server emits ``partial`` and ``final`` JSON messages on the same
  WebSocket. We dispatch them to two queues so the conversation loop only
  sees finals and the barge-in monitor only sees partials.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import structlog
import websockets

try:
    import audioop                        # type: ignore[import-untyped]
except ImportError:                                          # pragma: no cover
    import audioop_lts as audioop         # type: ignore[no-redef]

from .metrics import M_STT_FINAL_LATENCY

log = structlog.get_logger().bind(component="audio_in")


@dataclass
class STTFinal:
    text: str
    duration_ms: int
    received_at: float


@dataclass
class STTPartial:
    text: str
    stability: float
    received_at: float


class AudioInPipeline:
    """Owns the STT WebSocket for one call.

    Inbound 8 kHz frames are pushed via ``feed()``; ``run()`` ships them to
    STT and dispatches transcripts to ``finals_queue`` and ``partials_queue``.
    """

    def __init__(
        self,
        stt_ws_url: str,
        language: str,
        finals_queue: asyncio.Queue,
        partials_queue: asyncio.Queue,
    ) -> None:
        self.stt_ws_url = stt_ws_url
        self.language = language
        self.finals_queue = finals_queue
        self.partials_queue = partials_queue

        self._frames_in: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
        self._ratecv_state: Any = None
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._stop = asyncio.Event()
        self._last_speech_end_at: float | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def feed(self, pcm_8k_s16: bytes) -> None:
        """Push one inbound PCM frame from the SIP socket. Non-blocking."""
        try:
            self._frames_in.put_nowait(pcm_8k_s16)
        except asyncio.QueueFull:
            log.warning("stt_input_queue_full",
                        dropped_bytes=len(pcm_8k_s16))

    def mark_speech_end(self) -> None:
        """Caller hint: timestamp the user's apparent end-of-speech.

        Used to bucket the STT-final latency metric. Not currently surfaced
        by the SIP layer (no VAD on that side); call sites can set it after
        a configurable silence window.
        """
        self._last_speech_end_at = time.monotonic()

    async def run(self) -> None:
        """Connect + run send/recv loops. Returns on stop or upstream EOF."""
        try:
            async with websockets.connect(
                self.stt_ws_url,
                max_size=8 * 1024 * 1024,
                ping_interval=20,
                ping_timeout=10,
            ) as ws:
                self._ws = ws
                await ws.send(json.dumps({
                    "type": "start",
                    "language": self.language,
                    "sample_rate": 16000,
                }))
                send_task = asyncio.create_task(self._send_loop(),
                                                name="stt-send")
                recv_task = asyncio.create_task(self._recv_loop(),
                                                name="stt-recv")
                done, pending = await asyncio.wait(
                    {send_task, recv_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                for t in done:
                    if t.exception():
                        log.warning("stt_task_error",
                                    task=t.get_name(),
                                    error=str(t.exception()))
        except (OSError, websockets.WebSocketException) as exc:
            log.warning("stt_connect_failed", error=str(exc))
        finally:
            self._ws = None

    async def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({"type": "end"}))
            except Exception:                                # pragma: no cover
                pass
            try:
                await self._ws.close()
            except Exception:                                # pragma: no cover
                pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _send_loop(self) -> None:
        while not self._stop.is_set():
            try:
                frame = await asyncio.wait_for(self._frames_in.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            up, self._ratecv_state = audioop.ratecv(
                frame, 2, 1, 8000, 16000, self._ratecv_state
            )
            try:
                await self._ws.send(up)
            except websockets.ConnectionClosed:
                return
            except Exception as exc:                         # pragma: no cover
                log.warning("stt_send_failed", error=str(exc))
                return

    async def _recv_loop(self) -> None:
        while not self._stop.is_set():
            try:
                msg = await self._ws.recv()
            except websockets.ConnectionClosed:
                return
            except Exception as exc:                         # pragma: no cover
                log.warning("stt_recv_failed", error=str(exc))
                return

            try:
                data = json.loads(msg)
            except (json.JSONDecodeError, TypeError):
                log.warning("stt_msg_invalid", msg_preview=str(msg)[:120])
                continue

            kind = data.get("type")
            now = time.monotonic()
            if kind == "partial":
                await self.partials_queue.put(STTPartial(
                    text=str(data.get("text", "")),
                    stability=float(data.get("stability", 0.0)),
                    received_at=now,
                ))
            elif kind == "final":
                if self._last_speech_end_at is not None:
                    M_STT_FINAL_LATENCY.observe(now - self._last_speech_end_at)
                    self._last_speech_end_at = None
                await self.finals_queue.put(STTFinal(
                    text=str(data.get("text", "")).strip(),
                    duration_ms=int(data.get("duration_ms", 0)),
                    received_at=now,
                ))
            elif kind == "error":
                log.warning("stt_error_from_server",
                            message=str(data.get("message", "")))
