"""TTS service entrypoint."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from . import cloner, synthesizer
from .backends import make_backend
from .config import TTSConfig, load_config
from .voice_store import VoiceStore


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _setup_logging(level: str) -> structlog.stdlib.BoundLogger:
    log_level = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().handlers = [handler]
    logging.getLogger().setLevel(log_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    return structlog.get_logger().bind(service="tts")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

M_REQ = Counter(
    "aipanel_tts_requests_total", "TTS requests", ["route", "status"]
)
M_LAT = Histogram(
    "aipanel_tts_request_seconds", "TTS request latency", ["route"],
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
M_INFLIGHT = Gauge(
    "aipanel_tts_inflight", "Active TTS requests"
)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

def _gpu_mem_used_mb() -> int:
    try:
        import pynvml  # type: ignore[import-untyped]
        pynvml.nvmlInit()
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            return int(info.used / (1024 * 1024))
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return 0


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg: TTSConfig = load_config()
    log = _setup_logging(cfg.log_level)

    log.info("startup",
             backend=cfg.backend, device=cfg.device,
             listen=f"{cfg.listen_host}:{cfg.listen_port}")

    backend = make_backend(
        cfg.backend,
        device=cfg.device,
        voices_dir=cfg.voices_dir,
        models_dir=cfg.models_dir,
    )
    voice_store = VoiceStore(db_dsn=cfg.db_dsn)

    app.state.cfg = cfg
    app.state.log = log
    app.state.backend = backend
    app.state.voice_store = voice_store
    app.state.loaded_at = datetime.now(timezone.utc)
    app.state.shutting_down = False
    app.state.inflight = 0

    log.info("ready", backend=cfg.backend)
    try:
        yield
    finally:
        app.state.shutting_down = True
        log.info("shutdown_started")
        deadline = asyncio.get_event_loop().time() + 30.0
        while app.state.inflight > 0 and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.5)
        try:
            backend.shutdown()
        except Exception:                                    # pragma: no cover
            log.exception("backend_shutdown_failed")
        log.info("shutdown_complete")


app = FastAPI(lifespan=lifespan)
app.include_router(synthesizer.router)
app.include_router(cloner.router)


@app.middleware("http")
async def _guard(request: Request, call_next):
    if app.state.shutting_down and request.url.path != "/health":
        return JSONResponse({"error": "service shutting down"},
                            status_code=503)
    app.state.inflight += 1
    M_INFLIGHT.set(app.state.inflight)
    try:
        return await call_next(request)
    finally:
        app.state.inflight -= 1
        M_INFLIGHT.set(app.state.inflight)


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    cfg: TTSConfig = request.app.state.cfg
    return JSONResponse({
        "status": "ok",
        "model": cfg.backend,
        "device": cfg.device,
        "gpu_mem_used_mb": _gpu_mem_used_mb(),
        "loaded_at": request.app.state.loaded_at.isoformat(),
    })


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def main() -> int:
    cfg = load_config()
    uvicorn.run(
        "aipanel_tts.main:app",
        host=cfg.listen_host,
        port=cfg.listen_port,
        log_config=None,
        access_log=False,
        workers=1,
    )
    return 0


if __name__ == "__main__":     # pragma: no cover
    sys.exit(main())
