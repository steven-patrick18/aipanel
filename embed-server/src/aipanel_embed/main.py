"""FastAPI app: POST /v1/embed and POST /v1/embed/batch."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest, start_http_server,
)
from pydantic import BaseModel, Field

from .config import EmbedConfig, load_config
from .model_loader import get_loaded, load_model

# ---------------------------------------------------------------------------
# Logging (matches the rest of the stack)
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
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    return structlog.get_logger().bind(service="embed")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
M_REQS = Counter("aipanel_embed_requests_total", "Embed requests", ["route"])
M_LAT  = Histogram("aipanel_embed_seconds", "Embed latency", ["route"],
                   buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class EmbedRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)


class EmbedBatchRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=64)


class EmbedResponse(BaseModel):
    embedding: list[float]
    dim: int
    model: str


class EmbedBatchResponse(BaseModel):
    embeddings: list[list[float]]
    dim: int
    model: str


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg = load_config()
    log = _setup_logging(cfg.log_level)
    app.state.cfg = cfg
    app.state.log = log
    start_http_server(cfg.metrics_port, addr=cfg.metrics_host)
    # Heavy load synchronously — service shouldn't accept requests before
    # the model is in memory. systemd TimeoutStartSec=300 is the outer bound.
    await asyncio.to_thread(load_model, cfg)
    log.info("ready")
    try:
        yield
    finally:
        log.info("shutdown")


app = FastAPI(lifespan=lifespan, title="aipanel-embed", version="0.12.0")


@app.get("/health")
async def health() -> JSONResponse:
    m = get_loaded()
    if m is None:
        return JSONResponse({"status": "loading"}, status_code=503)
    return JSONResponse({
        "status":     "ok",
        "model":      m.name,
        "dim":        m.dim,
        "device":     m.device,
        "loaded_at":  m.loaded_at.isoformat(),
    })


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _embed_sync(texts: list[str]) -> list[list[float]]:
    """Synchronous embed call — wrapped in to_thread by the route."""
    m = get_loaded()
    if m is None:
        raise RuntimeError("model not loaded")
    # bge-m3 returns numpy by default; tolist for JSON.
    out = m.model.encode(
        texts,
        normalize_embeddings=True,    # cosine-ready
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return out.tolist() if hasattr(out, "tolist") else [list(v) for v in out]


@app.post("/v1/embed", response_model=EmbedResponse)
async def embed_one(req: EmbedRequest) -> EmbedResponse:
    M_REQS.labels(route="embed").inc()
    with M_LAT.labels(route="embed").time():
        vecs = await asyncio.to_thread(_embed_sync, [req.text])
    m = get_loaded()
    return EmbedResponse(embedding=vecs[0], dim=m.dim, model=m.name)


@app.post("/v1/embed/batch", response_model=EmbedBatchResponse)
async def embed_batch(req: EmbedBatchRequest) -> EmbedBatchResponse:
    cfg: EmbedConfig = app.state.cfg
    if len(req.texts) > cfg.max_batch:
        raise HTTPException(
            status_code=400,
            detail=f"batch larger than max_batch={cfg.max_batch}",
        )
    M_REQS.labels(route="embed_batch").inc()
    with M_LAT.labels(route="embed_batch").time():
        vecs = await asyncio.to_thread(_embed_sync, list(req.texts))
    m = get_loaded()
    return EmbedBatchResponse(embeddings=vecs, dim=m.dim, model=m.name)


def main() -> int:
    cfg = load_config()
    uvicorn.run(
        "aipanel_embed.main:app",
        host=cfg.listen_host,
        port=cfg.listen_port,
        log_config=None,
        access_log=False,
        workers=1,
    )
    return 0


if __name__ == "__main__":   # pragma: no cover
    sys.exit(main())
