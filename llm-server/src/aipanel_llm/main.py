"""LLM service: FastAPI proxy in front of vLLM.

Routes
------
* ``GET  /health``                    — aipanel JSON {status, model, gpu_mem_used_mb, loaded_at}
* ``GET  /metrics``                   — our counters + concatenated vLLM metrics
* ``ANY  /v1/{path:path}``            — reverse-proxied to vLLM (streams SSE)
* ``ANY  /vllm/{path:path}``          — escape hatch onto vLLM's full surface

Lifespan
--------
On startup: spawn vLLM, await ``/health`` 200 OK (≤300 s), then mark ready.
On SIGTERM: middleware starts returning 503; we wait up to 30 s for in-flight
requests; then SIGTERM the vLLM child.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx
import structlog
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from .config import LLMConfig, load_config
from .launcher import VLLMSubprocess

# ---------------------------------------------------------------------------
# Logging — JSON to stdout, systemd captures it.
# ---------------------------------------------------------------------------

def _setup_logging(level: str) -> structlog.stdlib.BoundLogger:
    log_level = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)

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
    return structlog.get_logger().bind(service="llm")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
M_REQ = Counter(
    "aipanel_llm_proxy_requests_total",
    "Requests proxied to vLLM",
    ["route", "status"],
)
M_LAT = Histogram(
    "aipanel_llm_proxy_request_seconds",
    "End-to-end latency of proxied requests",
    ["route"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
M_INFLIGHT = Gauge(
    "aipanel_llm_proxy_inflight",
    "Currently-in-flight proxied requests",
)
M_VLLM_UP = Gauge(
    "aipanel_llm_vllm_up",
    "1 if vLLM is reachable, 0 otherwise",
)


# ---------------------------------------------------------------------------
# Per-process state
# ---------------------------------------------------------------------------

class State:
    cfg: LLMConfig
    vllm: VLLMSubprocess
    client: httpx.AsyncClient
    log: structlog.stdlib.BoundLogger
    loaded_at: datetime | None = None
    shutting_down: bool = False
    inflight: int = 0
    inflight_lock: asyncio.Lock


state = State()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _http_health_ok(url: str) -> bool:
    """Probe used by VLLMSubprocess.wait_ready."""
    try:
        r = await state.client.get(url, timeout=2.0)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def _gpu_mem_used_mb() -> int:
    """Best-effort GPU memory query. Returns 0 on CPU-only or pynvml absent."""
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


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    state.cfg = load_config()
    state.log = _setup_logging(state.cfg.log_level)
    state.inflight_lock = asyncio.Lock()
    state.client = httpx.AsyncClient(
        base_url=state.cfg.internal_base_url,
        timeout=httpx.Timeout(state.cfg.request_timeout_sec, connect=5.0),
    )

    state.log.info("startup",
                   model=state.cfg.model,
                   listen=f"{state.cfg.listen_host}:{state.cfg.listen_port}",
                   internal_port=state.cfg.internal_port)

    state.vllm = VLLMSubprocess(state.cfg)
    state.vllm.start()

    ready = await state.vllm.wait_ready(_http_health_ok, timeout_sec=300.0)
    if ready:
        state.loaded_at = datetime.now(timezone.utc)
        M_VLLM_UP.set(1)
        state.log.info("ready")
    else:
        # Stay up so /health reports the failure clearly. systemd will
        # eventually decide to restart on TimeoutStartSec.
        state.log.error("vllm_failed_to_start")

    try:
        yield
    finally:
        state.shutting_down = True
        state.log.info("shutdown_started")
        # Drain in-flight requests up to 30 s.
        deadline = asyncio.get_event_loop().time() + 30.0
        while state.inflight > 0 and asyncio.get_event_loop().time() < deadline:
            state.log.info("draining", inflight=state.inflight)
            await asyncio.sleep(0.5)

        await state.client.aclose()
        state.vllm.terminate(grace_sec=30.0)
        state.log.info("shutdown_complete")


app = FastAPI(lifespan=lifespan)


# ---------------------------------------------------------------------------
# Middleware: 503 once shutting down
# ---------------------------------------------------------------------------

@app.middleware("http")
async def _shutdown_gate(request: Request, call_next):
    if state.shutting_down and request.url.path != "/health":
        return JSONResponse(
            {"error": "service shutting down"}, status_code=503
        )
    return await call_next(request)


# ---------------------------------------------------------------------------
# /health, /metrics
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> JSONResponse:
    if state.loaded_at is None:
        return JSONResponse(
            {
                "status": "loading",
                "model": state.cfg.model,
                "gpu_mem_used_mb": _gpu_mem_used_mb(),
                "loaded_at": None,
            },
            status_code=503,
        )
    if not state.vllm.is_alive():
        M_VLLM_UP.set(0)
        return JSONResponse(
            {
                "status": "vllm_down",
                "model": state.cfg.model,
                "gpu_mem_used_mb": _gpu_mem_used_mb(),
                "loaded_at": state.loaded_at.isoformat(),
            },
            status_code=503,
        )
    return JSONResponse(
        {
            "status": "ok",
            "model": state.cfg.model,
            "gpu_mem_used_mb": _gpu_mem_used_mb(),
            "loaded_at": state.loaded_at.isoformat(),
        }
    )


@app.get("/metrics")
async def metrics() -> Response:
    """Concatenate our wrapper metrics with vLLM's native ones."""
    body = generate_latest()
    try:
        r = await state.client.get("/metrics", timeout=2.0)
        if r.status_code == 200:
            body += b"\n# --- vLLM metrics ---\n" + r.content
    except httpx.HTTPError:
        pass
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# Reverse proxy
# ---------------------------------------------------------------------------

# Hop-by-hop headers per RFC 7230 §6.1 — must be stripped.
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "host",
}


def _strip_headers(headers) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP}


async def _proxy(prefix: str, path: str, request: Request) -> Response:
    """Generic streaming reverse proxy onto state.client."""
    target = f"/{prefix}/{path}" if prefix else f"/{path}"
    body = await request.body()
    rebuilt = state.client.build_request(
        request.method,
        target,
        params=dict(request.query_params),
        headers=_strip_headers(request.headers),
        content=body,
    )

    async with state.inflight_lock:
        state.inflight += 1
        M_INFLIGHT.set(state.inflight)
    started = time.monotonic()
    route_label = f"/{prefix}/*" if prefix else f"/{path.split('/', 1)[0]}/*"

    try:
        response = await state.client.send(rebuilt, stream=True)
    except httpx.HTTPError as exc:
        async with state.inflight_lock:
            state.inflight -= 1
            M_INFLIGHT.set(state.inflight)
        M_REQ.labels(route=route_label, status="502").inc()
        state.log.warning("proxy_upstream_error",
                          target=target, error=str(exc))
        return JSONResponse({"error": "upstream unavailable"}, status_code=502)

    async def _stream() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        finally:
            await response.aclose()
            async with state.inflight_lock:
                state.inflight -= 1
                M_INFLIGHT.set(state.inflight)
            M_LAT.labels(route=route_label).observe(time.monotonic() - started)
            M_REQ.labels(route=route_label,
                         status=str(response.status_code)).inc()

    return StreamingResponse(
        _stream(),
        status_code=response.status_code,
        headers=_strip_headers(response.headers),
        media_type=response.headers.get("content-type"),
    )


@app.api_route("/v1/{path:path}",
               methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_v1(path: str, request: Request) -> Response:
    return await _proxy("v1", path, request)


@app.api_route("/vllm/{path:path}",
               methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_passthrough(path: str, request: Request) -> Response:
    return await _proxy("", path, request)


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main() -> int:
    cfg = load_config()
    uvicorn.run(
        "aipanel_llm.main:app",
        host=cfg.listen_host,
        port=cfg.listen_port,
        log_config=None,           # we configure logging in lifespan
        access_log=False,
        workers=1,                 # single-worker; vLLM holds the GPU
    )
    return 0


if __name__ == "__main__":     # pragma: no cover
    sys.exit(main())
