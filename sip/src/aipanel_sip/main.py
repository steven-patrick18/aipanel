"""SIP service entrypoint.

Run as:    python -m aipanel_sip.main      (or via the aipanel-sip console_script)

Lifecycle:

    load config → setup logging → start metrics HTTP server →
    start PJSIP endpoint → load + register accounts (staggered) →
    block on signals → on SIGTERM: drain calls, BYE, unregister, exit.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from types import FrameType

import redis
import structlog
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from .account_manager import AccountManager
from .call_handler import CallRouter, CallState
from .config import load_config
from .endpoint import SipEndpoint
from .logging_setup import setup_logging
from .worker_dispatcher import WorkerDispatcher

# ---------------------------------------------------------------------------
# Prometheus metrics — module-level so any component can reference them
# ---------------------------------------------------------------------------
M_REGS = Counter(
    "aipanel_sip_registrations_total",
    "SIP registration outcomes",
    ["status"],
)
M_CALLS_ACTIVE = Gauge(
    "aipanel_sip_calls_active",
    "Currently bridged calls",
)
M_CALLS_TOTAL = Counter(
    "aipanel_sip_calls_total",
    "Calls handled, by outcome",
    ["outcome"],
)
M_FRAMES_DROPPED = Counter(
    "aipanel_sip_audio_frames_dropped_total",
    "Audio frames dropped due to queue overflow",
)
M_REG_LATENCY = Histogram(
    "aipanel_sip_register_latency_seconds",
    "Time from REGISTER request to 200 OK",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main() -> int:
    cfg = load_config()
    log = setup_logging(level=cfg.log_level)
    log.info("startup", version="0.3.0",
             listen=f"{cfg.sip_listen_host}:{cfg.sip_listen_port}")

    # Runtime dir for unix sockets. systemd's RuntimeDirectory= creates this
    # ahead of us, but mkdir(exist_ok) is cheap insurance.
    os.makedirs(cfg.runtime_dir, exist_ok=True)

    # Prometheus on a loopback-only listener.
    start_http_server(cfg.metrics_port, addr=cfg.metrics_host)
    log.info("metrics_listening",
             addr=f"{cfg.metrics_host}:{cfg.metrics_port}")

    # External services.
    redis_client = redis.Redis.from_url(cfg.redis_url, decode_responses=False)
    try:
        redis_client.ping()
    except redis.RedisError as exc:
        log.error("redis_unreachable", error=str(exc))
        return 2

    # PJSIP endpoint.
    endpoint = SipEndpoint(cfg)
    endpoint.start()

    # Per-call state and routing.
    state = CallState()
    dispatcher = WorkerDispatcher(redis_client, cfg.worker_request_stream)

    def _on_call_ended(outcome: str) -> None:
        M_CALLS_TOTAL.labels(outcome=outcome).inc()
        M_CALLS_ACTIVE.set(state.active_count())

    def _on_frame_dropped() -> None:
        M_FRAMES_DROPPED.inc()

    router = CallRouter(
        endpoint=endpoint,
        cfg=cfg,
        state=state,
        dispatcher=dispatcher,
        on_call_ended=_on_call_ended,
        on_frame_dropped=_on_frame_dropped,
    )

    # When CallRouter answers, bump the gauge.
    _orig_handle = router.handle_invite

    def _wrapped_handle(account, prm):
        before = state.active_count()
        _orig_handle(account, prm)
        if state.active_count() > before:
            M_CALLS_ACTIVE.set(state.active_count())
    router.handle_invite = _wrapped_handle  # type: ignore[method-assign]

    # Account manager — wires reg metrics + incoming-call routing.
    accounts = AccountManager(
        endpoint=endpoint,
        cfg=cfg,
        db_dsn=cfg.db_dsn,
        redis_client=redis_client,
        on_incoming_call=router.handle_invite,
        on_reg_success=lambda: M_REGS.labels(status="active").inc(),
        on_reg_failure=lambda: M_REGS.labels(status="failed").inc(),
    )

    accounts.load_initial()
    accounts.start_pubsub_watcher()

    # ------------------------------------------------------------------
    # Graceful shutdown
    # ------------------------------------------------------------------
    shutdown_done = threading.Event()

    def _shutdown(signum: int, _frame: FrameType | None) -> None:
        if state.shutting_down:
            return
        state.shutting_down = True
        log.info("shutdown_started", signum=signum)

        deadline = time.monotonic() + cfg.shutdown_drain_sec
        while state.active_count() > 0 and time.monotonic() < deadline:
            log.info("shutdown_draining", active=state.active_count())
            time.sleep(0.5)

        if state.active_count() > 0:
            log.warning("shutdown_force_hangup", active=state.active_count())
            router.hangup_all()
            time.sleep(1.0)

        accounts.unregister_all()
        accounts.stop()
        # Brief grace for unregisters to flush.
        time.sleep(1.0)
        endpoint.shutdown()
        shutdown_done.set()
        log.info("shutdown_complete")

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    log.info("ready")
    # Block until shutdown_done is set. signal.pause() is unreliable here
    # because PJSIP installs its own SIGCHLD handlers; an event wait is
    # simpler and Windows-safe (not that we run on Windows).
    try:
        shutdown_done.wait()
    except KeyboardInterrupt:                                # pragma: no cover
        _shutdown(signal.SIGINT, None)

    return 0


if __name__ == "__main__":                                   # pragma: no cover
    sys.exit(main())
