"""ARQ worker process entrypoint.

Run as: ``python -m aipanel.jobs.arq_worker`` (also wired as the
``aipanel-jobs`` console script + systemd unit).

Adds a FastAPI dependency ``get_arq`` that hands routes a connection to the
same Redis ARQ uses, so they can ``enqueue_job`` without managing pools.
"""

from __future__ import annotations

import sys

import structlog
from arq import cron, run_worker
from arq.connections import ArqRedis, RedisSettings, create_pool

from ..config import get_config
from .analytics_rollup_job import analytics_rollup
from .backup_job import nightly_backup
from .campaign_mine_job import campaign_mine_few_shot
from .kb_ingest_job import kb_ingest_document
from .voice_clone_job import voice_clone

log = structlog.get_logger().bind(component="arq")


# ---------------------------------------------------------------------------
# Settings (consumed by `arq` CLI + by run_worker())
# ---------------------------------------------------------------------------

def _redis_settings() -> RedisSettings:
    cfg = get_config().redis
    return RedisSettings(
        host=cfg.host,
        port=cfg.port,
        database=cfg.db,
        password=cfg.password,
    )


class WorkerSettings:
    functions = [
        voice_clone, kb_ingest_document, nightly_backup,
        analytics_rollup, campaign_mine_few_shot,
    ]
    cron_jobs = [
        # Nightly backup at 03:30 UTC.
        cron(nightly_backup, hour={3}, minute={30}),
        # Hourly analytics rollup.
        cron(analytics_rollup, minute={5}),
        # Hourly campaign few-shot mine — picks up new successful calls.
        cron(campaign_mine_few_shot, minute={20}),
    ]
    job_timeout = 600
    max_jobs = 4
    keep_result = 3600
    redis_settings = _redis_settings()


# ---------------------------------------------------------------------------
# FastAPI integration
# ---------------------------------------------------------------------------

_pool: ArqRedis | None = None


async def init_arq_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(_redis_settings())
    return _pool


async def close_arq_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def get_arq() -> ArqRedis:
    """FastAPI dep — returns the shared ARQ connection pool."""
    if _pool is None:
        await init_arq_pool()
    assert _pool is not None
    return _pool


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def run() -> int:
    log.info("arq_worker_starting")
    run_worker(WorkerSettings)
    return 0


if __name__ == "__main__":   # pragma: no cover
    sys.exit(run())
