"""FastAPI app factory + uvicorn entrypoint.

Routes register under ``/api/v1``. OpenAPI docs at ``/api/docs`` are admin-
gated via a small dependency. All non-API requests should be served by
nginx (the React SPA), which is why we don't mount any frontend here.
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse

from .api.v1 import router as v1_router
from .auth.deps import CurrentUser
from .auth.permissions import require_admin
from .config import get_config
from .db.session import dispose_engine
from .jobs.arq_worker import close_arq_pool, init_arq_pool


# ---------------------------------------------------------------------------
# Logging — JSON to stdout (systemd captures into /var/log/aipanel/web.log).
# ---------------------------------------------------------------------------

def _setup_logging(level: str = "INFO") -> structlog.stdlib.BoundLogger:
    log_level = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)
    for noisy in ("uvicorn.access", "uvicorn.error", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
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
    return structlog.get_logger().bind(service="web")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log = _setup_logging()
    log.info("startup")
    await init_arq_pool()
    try:
        yield
    finally:
        log.info("shutdown_started")
        await close_arq_pool()
        await dispose_engine()
        log.info("shutdown_complete")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    cfg = get_config()
    # Disable the default docs URLs — we re-serve them admin-gated below.
    app = FastAPI(
        title="aipanel",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # --- exception handlers ---
    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "validation error", "errors": exc.errors()},
        )

    # --- routes ---
    app.include_router(v1_router)

    # Admin-only OpenAPI + Swagger UI.
    @app.get("/api/openapi.json", include_in_schema=False)
    async def openapi(_user=Depends(require_admin)) -> dict:
        return app.openapi()

    @app.get("/api/docs", include_in_schema=False)
    async def docs(_user=Depends(require_admin)):
        return get_swagger_ui_html(
            openapi_url="/api/openapi.json",
            title="aipanel API",
        )

    # Health for nginx upstream check (no auth).
    @app.get("/api/healthz", include_in_schema=False)
    async def healthz() -> dict:
        return {"ok": True}

    return app


# Module-level for `uvicorn aipanel.main:app`.
app = create_app()


# ---------------------------------------------------------------------------
# uvicorn entrypoint
# ---------------------------------------------------------------------------

def main() -> int:
    cfg = get_config().panel
    uvicorn.run(
        "aipanel.main:app",
        host=cfg.listen_host,
        port=cfg.listen_port,
        log_config=None,
        access_log=False,
        workers=1,
    )
    return 0


if __name__ == "__main__":   # pragma: no cover
    sys.exit(main())
