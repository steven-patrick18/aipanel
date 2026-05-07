"""STT service entrypoint."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
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

from .config import STTConfig, load_config
from .model_loader import get_models, load_models

# ---------------------------------------------------------------------------
# Logging — shared shape with the SIP service.
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
    return structlog.get_logger().bind(service="stt")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
M_REQ = Counter(
    "aipanel_stt_requests_total", "STT requests", ["route", "status"]
)
M_LAT = Histogram(
    "aipanel_stt_request_seconds", "STT request latency", ["route"],
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
M_STREAMS = Gauge(
    "aipanel_stt_streams_active", "Active WS streams"
)


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

class State:
    cfg: STTConfig
    log: structlog.stdlib.BoundLogger
    shutting_down: bool = False
    inflight: int = 0


state = State()


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
    state.cfg = load_config()
    state.log = _setup_logging(state.cfg.log_level)

    state.log.info("startup",
                   model=state.cfg.model,
                   listen=f"{state.cfg.listen_host}:{state.cfg.listen_port}")
    # Heavy load synchronously — service shouldn't accept traffic before this
    # finishes. systemd's TimeoutStartSec=300 is the outer bound.
    await asyncio.to_thread(load_models, state.cfg)
    state.log.info("ready")

    try:
        yield
    finally:
        state.shutting_down = True
        state.log.info("shutdown_started")
        deadline = asyncio.get_event_loop().time() + 30.0
        while state.inflight > 0 and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.5)
        state.log.info("shutdown_complete")


app = FastAPI(lifespan=lifespan)

# Late import: streaming.router and transcribe.router both touch model_loader.
from . import streaming, transcribe  # noqa: E402

app.include_router(transcribe.router)
app.include_router(streaming.router)


@app.middleware("http")
async def _shutdown_gate(request: Request, call_next):
    if state.shutting_down and request.url.path != "/health":
        return JSONResponse(
            {"error": "service shutting down"}, status_code=503
        )
    state.inflight += 1
    try:
        return await call_next(request)
    finally:
        state.inflight -= 1


@app.get("/health")
async def health() -> JSONResponse:
    models = get_models()
    if models is None:
        return JSONResponse(
            {
                "status": "loading",
                "model": state.cfg.model if hasattr(state, "cfg") else None,
                "gpu_mem_used_mb": _gpu_mem_used_mb(),
                "loaded_at": None,
            },
            status_code=503,
        )
    return JSONResponse({
        "status": "ok",
        "model": state.cfg.model,
        "device": models.device,
        "compute_type": models.compute_type,
        "gpu_mem_used_mb": _gpu_mem_used_mb(),
        "loaded_at": models.loaded_at.isoformat(),
    })


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def main() -> int:
    cfg = load_config()
    uvicorn.run(
        "aipanel_stt.main:app",
        host=cfg.listen_host,
        port=cfg.listen_port,
        log_config=None,
        access_log=False,
        workers=1,
    )
    return 0


if __name__ == "__main__":     # pragma: no cover
    sys.exit(main())
