"""Process entrypoint: wire up the three loops + FastAPI."""

from __future__ import annotations

import asyncio
import os
import signal
import sys

import redis.asyncio as aioredis
import uvicorn
from prometheus_client import start_http_server

from .adapters import get_adapter
from .api import make_app
from .config import SessionMgrConfig, load_config
from .heartbeat import HeartbeatScheduler
from .logging_setup import setup_logging
from .login import BrowserPool
from .session_supervisor import SessionSupervisor


async def _run(cfg: SessionMgrConfig) -> int:
    log = setup_logging(level=cfg.log_level)
    log.info("startup",
             listen=f"{cfg.listen_host}:{cfg.listen_port}",
             adapter=cfg.adapter,
             browser_pool=cfg.browser_pool_size)

    encryption_key = os.environ.get("ENCRYPTION_KEY", "")
    if not encryption_key:
        log.error("encryption_key_missing")
        return 2

    # Prometheus on its own port.
    start_http_server(cfg.metrics_port, addr=cfg.metrics_host)
    log.info("metrics_listening",
             addr=f"{cfg.metrics_host}:{cfg.metrics_port}")

    # Redis.
    redis_client = aioredis.from_url(cfg.redis_url, decode_responses=False)
    try:
        await redis_client.ping()
    except aioredis.RedisError as exc:
        log.error("redis_unreachable", error=str(exc))
        return 2

    # Adapter + browser pool.
    adapter = get_adapter(cfg.adapter)
    browser_pool = BrowserPool(
        size=cfg.browser_pool_size,
        browsers_path=cfg.playwright_browsers_path,
    )
    try:
        await browser_pool.start()
    except Exception as exc:
        log.error("browser_pool_start_failed", error=str(exc))
        await redis_client.aclose()
        return 2

    # Supervisor + heartbeat scheduler.
    supervisor = SessionSupervisor(
        adapter=adapter,
        browser_pool=browser_pool,
        redis_client=redis_client,
        encryption_key=encryption_key,
        db_dsn=cfg.db_dsn,
        poll_interval_sec=cfg.supervisor_poll_interval_sec,
        login_backoff_sec=tuple(cfg.login_backoff_sec),
        login_timeout_sec=cfg.browser_login_timeout_sec,
        screenshot_dir=cfg.browser_screenshot_dir,
    )
    heartbeat = HeartbeatScheduler(
        supervisor,
        interval_sec=cfg.heartbeat_interval_sec,
        max_concurrency=cfg.heartbeat_max_concurrency,
    )

    # FastAPI app.
    app = make_app(cfg, supervisor)
    server_config = uvicorn.Config(
        app,
        host=cfg.listen_host,
        port=cfg.listen_port,
        log_config=None,
        access_log=False,
        loop="asyncio",
        workers=1,
    )
    server = uvicorn.Server(server_config)

    shutdown_event = asyncio.Event()

    def _signal(_sig: int) -> None:
        log.info("shutdown_signal", sig=_sig)
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, lambda: _signal(signal.SIGTERM))
    loop.add_signal_handler(signal.SIGINT, lambda: _signal(signal.SIGINT))

    log.info("ready")

    server_task = asyncio.create_task(server.serve(), name="uvicorn")
    sup_task = asyncio.create_task(supervisor.run(), name="supervisor")
    hb_task = asyncio.create_task(heartbeat.run(), name="heartbeat")

    await shutdown_event.wait()
    log.info("shutdown_started")

    server.should_exit = True
    await heartbeat.stop()
    await supervisor.stop_all()
    await browser_pool.stop()

    for t in (server_task, sup_task, hb_task):
        t.cancel()
    await asyncio.gather(server_task, sup_task, hb_task, return_exceptions=True)
    await redis_client.aclose()
    log.info("shutdown_complete")
    return 0


def main() -> int:
    cfg = load_config()
    return asyncio.run(_run(cfg))


if __name__ == "__main__":   # pragma: no cover
    sys.exit(main())
