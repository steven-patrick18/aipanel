"""Worker process entrypoint.

Pulls jobs from Redis (list ``calls:incoming`` first, stream
``aipanel:worker_requests`` as fallback so we work with both prompt 3's
SIP service and prompt 6's spec). Spawns up to ``--concurrency`` concurrent
``CallSession`` tasks. SIGTERM stops accepting new jobs and waits up to 30 s
for active calls to finish before exit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import socket
import sys
from typing import Any

import redis.asyncio as aioredis
from prometheus_client import start_http_server

from .call_session import CallJob, CallSession, WorkerServices
from .config import WorkerConfig, load_config
from .logging_setup import setup_logging
from .metrics import M_CALLS


# ---------------------------------------------------------------------------
# Job sources
# ---------------------------------------------------------------------------

class JobSource:
    """Reads the next job, preferring the BRPOP list source."""

    def __init__(self, r: aioredis.Redis, cfg: WorkerConfig) -> None:
        self._r = r
        self._cfg = cfg
        self._stream_initialised = False

    async def next_job(self, timeout_sec: float) -> dict | None:
        # 1. BRPOP from the list (spec).
        try:
            res = await self._r.brpop(self._cfg.queue_list_key, timeout=timeout_sec)
        except aioredis.RedisError:
            res = None
        if res is not None:
            _key, payload = res
            return _decode(payload)

        # 2. XREADGROUP on the stream (compat with prompt 3's SIP service).
        await self._ensure_stream_group()
        try:
            entries = await self._r.xreadgroup(
                groupname=self._cfg.queue_consumer_group,
                consumername=socket.gethostname(),
                streams={self._cfg.queue_stream_key: ">"},
                count=1,
                block=int(timeout_sec * 1000),
            )
        except aioredis.RedisError:
            return None
        if not entries:
            return None
        _stream, items = entries[0]
        if not items:
            return None
        msg_id, fields = items[0]
        # ack immediately — we own the call from here.
        try:
            await self._r.xack(self._cfg.queue_stream_key,
                               self._cfg.queue_consumer_group, msg_id)
        except aioredis.RedisError:                          # pragma: no cover
            pass
        return _decode_stream_fields(fields)

    async def _ensure_stream_group(self) -> None:
        if self._stream_initialised:
            return
        try:
            await self._r.xgroup_create(
                name=self._cfg.queue_stream_key,
                groupname=self._cfg.queue_consumer_group,
                id="$",
                mkstream=True,
            )
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):                  # pragma: no cover
                raise
        self._stream_initialised = True


def _decode(payload: Any) -> dict | None:
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", "replace")
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None
    if isinstance(payload, dict):
        return payload
    return None


def _decode_stream_fields(fields: dict) -> dict:
    """Stream fields come as a flat dict; everything's already strings."""
    out: dict = {}
    for k, v in fields.items():
        if isinstance(k, bytes):
            k = k.decode("utf-8", "replace")
        if isinstance(v, bytes):
            v = v.decode("utf-8", "replace")
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# Reservation
# ---------------------------------------------------------------------------

async def _reserve(r: aioredis.Redis, call_id: str, ttl: int) -> bool:
    """SETNX-equivalent reservation so two workers don't double-handle a call."""
    key = f"calls:active:{call_id}"
    return await r.set(key, "1", nx=True, ex=ttl)


async def _release(r: aioredis.Redis, call_id: str) -> None:
    try:
        await r.delete(f"calls:active:{call_id}")
    except aioredis.RedisError:                              # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# Run a single call (with full top-level error catch)
# ---------------------------------------------------------------------------

async def _run_one_call(job: CallJob, services: WorkerServices, log) -> None:
    log.info("call_start",
             call_id=job.call_id, deployment_id=job.deployment_id)
    try:
        async with CallSession(job, services) as session:
            await session.run()
    except Exception as exc:
        log.exception("call_crashed",
                      call_id=job.call_id, error=str(exc))
        M_CALLS.labels(outcome="error").inc()


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------

async def _supervisor(cfg: WorkerConfig, services: WorkerServices, log) -> int:
    r = aioredis.from_url(cfg.redis_url, decode_responses=False)
    try:
        await r.ping()
    except aioredis.RedisError as exc:
        log.error("redis_unreachable", error=str(exc))
        return 2

    job_source = JobSource(r, cfg)
    sem = asyncio.Semaphore(cfg.concurrency)
    shutting_down = asyncio.Event()
    active: set[asyncio.Task] = set()

    def _signal_handler(signum: int) -> None:
        log.info("shutdown_signal", signum=signum)
        shutting_down.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM,
                            lambda: _signal_handler(signal.SIGTERM))
    loop.add_signal_handler(signal.SIGINT,
                            lambda: _signal_handler(signal.SIGINT))

    log.info("supervisor_ready",
             concurrency=cfg.concurrency,
             redis=cfg.redis_url.split("@")[-1])

    while not shutting_down.is_set():
        await sem.acquire()
        try:
            payload = await job_source.next_job(timeout_sec=2.0)
        except Exception as exc:                             # pragma: no cover
            log.warning("job_pull_failed", error=str(exc))
            sem.release()
            await asyncio.sleep(1.0)
            continue
        if payload is None:
            sem.release()
            continue

        try:
            job = CallJob.from_payload(payload)
        except (ValueError, KeyError) as exc:
            log.warning("job_payload_invalid", error=str(exc), payload=payload)
            sem.release()
            continue
        if not job.call_id or not job.sip_socket_path:
            log.warning("job_missing_fields", payload=payload)
            sem.release()
            continue

        if not await _reserve(r, job.call_id, cfg.reservation_ttl_sec):
            log.info("call_already_reserved", call_id=job.call_id)
            sem.release()
            continue

        async def _wrapped(j: CallJob) -> None:
            try:
                await _run_one_call(j, services, log)
            finally:
                await _release(r, j.call_id)
                sem.release()

        task = asyncio.create_task(_wrapped(job), name=f"call-{job.call_id}")
        active.add(task)
        task.add_done_callback(active.discard)

    # Drain phase.
    log.info("draining", active=len(active),
             deadline_sec=cfg.shutdown_drain_sec)
    try:
        await asyncio.wait_for(
            asyncio.gather(*active, return_exceptions=True),
            timeout=cfg.shutdown_drain_sec,
        )
    except asyncio.TimeoutError:
        log.warning("drain_timeout_force_cancel", remaining=len(active))
        for t in active:
            t.cancel()
        await asyncio.gather(*active, return_exceptions=True)

    await r.aclose()
    log.info("supervisor_stopped")
    return 0


# ---------------------------------------------------------------------------
# Service handles bootstrap
# ---------------------------------------------------------------------------

def _make_minio(cfg: WorkerConfig):
    if not cfg.minio_access_key or not cfg.minio_secret_key:
        return None
    try:
        from minio import Minio
    except ImportError:                                      # pragma: no cover
        return None
    return Minio(
        cfg.minio_endpoint,
        access_key=cfg.minio_access_key,
        secret_key=cfg.minio_secret_key,
        secure=cfg.minio_secure,
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(prog="aipanel-worker")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("AIPANEL_WORKER_CONCURRENCY", "0")) or None,
        help="Max concurrent calls (overrides config and env).",
    )
    args = parser.parse_args()

    cfg = load_config()
    if args.concurrency is not None and args.concurrency > 0:
        # Pydantic frozen — rebuild with override.
        cfg = cfg.model_copy(update={"concurrency": args.concurrency})

    log = setup_logging(level=cfg.log_level)
    log.info("startup", concurrency=cfg.concurrency, version="0.5.0")

    start_http_server(cfg.metrics_port, addr=cfg.metrics_host)
    log.info("metrics_listening",
             addr=f"{cfg.metrics_host}:{cfg.metrics_port}")

    services = WorkerServices(cfg=cfg, minio_client=_make_minio(cfg))

    return asyncio.run(_supervisor(cfg, services, log))


if __name__ == "__main__":   # pragma: no cover
    sys.exit(main())
