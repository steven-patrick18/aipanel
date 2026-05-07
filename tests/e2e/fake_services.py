"""In-process fakes for the LLM proxy, STT, TTS, and embed-server.

Each fake binds to 127.0.0.1:0 (random free port) and exposes the absolute
URL to the test. They satisfy the worker's expected request shapes and
return canned responses keyed off a tiny scripted plan.
"""

from __future__ import annotations

import asyncio
import json
import socket
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Fake LLM
# ---------------------------------------------------------------------------

def make_fake_llm_app(scripted_replies: list[str]) -> FastAPI:
    """Returns each scripted reply once per chat-completion call, then loops."""
    app = FastAPI()
    state = {"i": 0}

    @app.get("/health")
    async def _h():
        return {"status": "ok", "model": "fake-llm",
                "gpu_mem_used_mb": 0, "loaded_at": "2026-01-01T00:00:00Z"}

    @app.post("/v1/chat/completions")
    async def _chat(_req: Request):
        text = scripted_replies[state["i"] % len(scripted_replies)]
        state["i"] += 1
        return {
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "model": "fake-llm",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                      "total_tokens": 0},
        }
    return app


# ---------------------------------------------------------------------------
# Fake STT (WebSocket only, the worker doesn't use the REST path)
# ---------------------------------------------------------------------------

def make_fake_stt_app(scripted_finals: list[str]) -> FastAPI:
    app = FastAPI()
    state = {"i": 0}

    @app.get("/health")
    async def _h():
        return {"status": "ok", "model": "fake-stt",
                "device": "cpu", "compute_type": "int8",
                "gpu_mem_used_mb": 0, "loaded_at": "2026-01-01T00:00:00Z"}

    @app.websocket("/v1/stt/stream")
    async def _stream(ws: WebSocket):
        await ws.accept()
        try:
            while True:
                msg = await ws.receive()
                # Test scripts emit final transcripts after N silence frames.
                if msg.get("type") == "websocket.disconnect":
                    return
                # We just forward each "final" reply when we see at least
                # one binary frame — keeps the test deterministic.
                if "bytes" in msg and state["i"] < len(scripted_finals):
                    text = scripted_finals[state["i"]]
                    state["i"] += 1
                    await ws.send_text(json.dumps({
                        "type": "final",
                        "text": text,
                        "duration_ms": 1500,
                    }))
                if "text" in msg:
                    payload = json.loads(msg["text"])
                    if payload.get("type") == "end":
                        return
        except Exception:
            pass
    return app


# ---------------------------------------------------------------------------
# Fake TTS — emits silence (320-byte frames @ 8 kHz s16le)
# ---------------------------------------------------------------------------

def make_fake_tts_app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    async def _h():
        return {"status": "ok", "model": "fake-tts",
                "device": "cpu", "gpu_mem_used_mb": 0,
                "loaded_at": "2026-01-01T00:00:00Z"}

    @app.post("/v1/tts/synthesize")
    async def _synth(_req: Request):
        async def _stream():
            # 50 frames of silence = ~1 s of audio. The worker's audio_out
            # pipeline will chunk these into 320-byte SIP frames.
            silence = b"\x00" * 320
            for _ in range(50):
                yield silence
                await asyncio.sleep(0.02)
        return StreamingResponse(_stream(), media_type="audio/L16")
    return app


# ---------------------------------------------------------------------------
# Server harness — boot any FastAPI on a free port in-process
# ---------------------------------------------------------------------------

class _SubServer:
    def __init__(self, app: FastAPI, port: int) -> None:
        self.port = port
        self._config = uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning",
            log_config=None, access_log=False, loop="asyncio",
        )
        self._server = uvicorn.Server(self._config)
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._server.serve())
        # Wait for the socket to be listening.
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", self.port),
                                              timeout=0.1):
                    return
            except OSError:
                await asyncio.sleep(0.05)
        raise RuntimeError(f"sub-server on :{self.port} never came up")

    async def stop(self) -> None:
        if not self._task:
            return
        self._server.should_exit = True
        await asyncio.wait_for(self._task, timeout=5.0)


@asynccontextmanager
async def boot(app: FastAPI):
    """`async with boot(app) as port: ...`"""
    port = _free_port()
    s = _SubServer(app, port)
    await s.start()
    try:
        yield port
    finally:
        await s.stop()
