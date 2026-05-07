"""Loop A: poll Postgres for active deployments, diff against in-memory.

* New deployments → spawn ``SessionWorker.start()``
* Removed deployments → call ``SessionWorker.stop()``
* Sessions stuck > 60 s without a heartbeat → force re-login
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import UUID

import psycopg
import redis.asyncio as aioredis
import structlog
from cryptography.fernet import Fernet, InvalidToken

from .adapters.base import VicidialAdapter
from .login import BrowserPool
from .models import DeploymentRow
from .session_worker import SessionWorker

log = structlog.get_logger().bind(component="supervisor")


SQL_ACTIVE_DEPLOYMENTS = """
    SELECT d.id::text         AS deployment_id,
           d.tenant_id::text  AS tenant_id,
           d.vicidial_server_id::text AS vici_server_id,
           v.web_url          AS web_url,
           v.asterisk_host    AS asterisk_host,
           d.vici_user        AS vici_user,
           d.vici_pass_encrypted AS vici_pass_encrypted,
           d.phone_login      AS phone_login,
           d.phone_pass_encrypted AS phone_pass_encrypted,
           d.campaign_id      AS campaign_id,
           d.allowed_transfer_ingroups AS allowed_transfer_ingroups
      FROM deployments d
      JOIN vicidial_servers v ON d.vicidial_server_id = v.id
     WHERE d.status IN ('starting', 'running')
"""


class SessionSupervisor:
    def __init__(
        self,
        adapter: VicidialAdapter,
        browser_pool: BrowserPool,
        redis_client: aioredis.Redis,
        encryption_key: str,
        db_dsn: str,
        *,
        poll_interval_sec: float = 30.0,
        login_backoff_sec: tuple[int, ...] = (5, 30, 120, 600),
        login_timeout_sec: float = 30.0,
        unhealthy_after_sec: float = 60.0,
        screenshot_dir: str | None = None,
    ) -> None:
        self.adapter = adapter
        self.browser_pool = browser_pool
        self.redis = redis_client
        self.db_dsn = db_dsn
        self.poll_interval_sec = poll_interval_sec
        self.login_backoff_sec = login_backoff_sec
        self.login_timeout_sec = login_timeout_sec
        self.unhealthy_after_sec = unhealthy_after_sec
        self.screenshot_dir = screenshot_dir

        self._fernet = Fernet(encryption_key.encode("ascii"))
        self.workers: dict[str, SessionWorker] = {}
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        log.info("supervisor_start",
                 poll_interval_sec=self.poll_interval_sec)
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:                                # pragma: no cover
                log.exception("supervisor_tick_failed")
            try:
                await asyncio.wait_for(self._stop.wait(),
                                       timeout=self.poll_interval_sec)
            except asyncio.TimeoutError:
                continue

    async def stop_all(self) -> None:
        self._stop.set()
        # Stop every worker in parallel; bounded by network timeouts inside.
        await asyncio.gather(
            *(w.stop() for w in self.workers.values()),
            return_exceptions=True,
        )
        self.workers.clear()

    def get_worker(self, deployment_id: str) -> SessionWorker | None:
        return self.workers.get(deployment_id)

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        rows = await asyncio.to_thread(self._sync_fetch_deployments)
        active_ids = {r.deployment_id for r in rows}

        # Add / refresh.
        for r in rows:
            existing = self.workers.get(str(r.deployment_id))
            if existing is None:
                await self._start_worker(r)
            else:
                await self._maybe_recover_unhealthy(existing)

        # Remove: workers whose deployment_id is no longer in the active set.
        for did in list(self.workers.keys()):
            if UUID(did) not in active_ids:
                await self._stop_worker(did)

    async def _start_worker(self, deployment: DeploymentRow) -> None:
        log.info("worker_starting",
                 deployment_id=str(deployment.deployment_id))
        worker = SessionWorker(
            deployment=deployment,
            adapter=self.adapter,
            browser_pool=self.browser_pool,
            redis_client=self.redis,
            login_backoff_sec=self.login_backoff_sec,
            login_timeout_sec=self.login_timeout_sec,
            screenshot_dir=self.screenshot_dir,
        )
        self.workers[str(deployment.deployment_id)] = worker
        # Login is async + slow — schedule but don't block the supervisor.
        asyncio.create_task(
            worker.start(),
            name=f"vici-login-{deployment.deployment_id}",
        )

    async def _stop_worker(self, deployment_id: str) -> None:
        worker = self.workers.pop(deployment_id, None)
        if worker is None:
            return
        log.info("worker_stopping", deployment_id=deployment_id)
        try:
            await worker.stop()
        except Exception:                                    # pragma: no cover
            log.exception("worker_stop_failed",
                          deployment_id=deployment_id)

    async def _maybe_recover_unhealthy(self, worker: SessionWorker) -> None:
        last = worker.state.last_heartbeat_at
        if last is None:
            return
        if (time.time() - last) < self.unhealthy_after_sec:
            return
        log.warning("worker_heartbeat_stale_force_relogin",
                    deployment_id=worker.state.deployment_id,
                    age_sec=int(time.time() - last))
        # Bump failure counter so the next heartbeat triggers _maybe_recover.
        worker.state.heartbeat_failures = 99
        # Trigger immediately rather than waiting for the next heartbeat tick.
        asyncio.create_task(worker.heartbeat())

    # ------------------------------------------------------------------
    # DB
    # ------------------------------------------------------------------

    def _sync_fetch_deployments(self) -> list[DeploymentRow]:
        try:
            with psycopg.connect(self.db_dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(SQL_ACTIVE_DEPLOYMENTS)
                    rows = cur.fetchall()
                    cols = [d.name for d in cur.description]
        except psycopg.Error as exc:
            log.warning("supervisor_db_failed", error=str(exc))
            return []

        out: list[DeploymentRow] = []
        for row in rows:
            r = dict(zip(cols, row))
            try:
                vp = self._fernet.decrypt(
                    r["vici_pass_encrypted"].encode("ascii")
                ).decode("utf-8")
                pp = self._fernet.decrypt(
                    r["phone_pass_encrypted"].encode("ascii")
                ).decode("utf-8")
            except (InvalidToken, ValueError, AttributeError):
                log.error("deployment_secret_decrypt_failed",
                          deployment_id=r["deployment_id"])
                continue
            out.append(DeploymentRow(
                deployment_id=UUID(r["deployment_id"]),
                tenant_id=UUID(r["tenant_id"]),
                vici_server_id=UUID(r["vici_server_id"]),
                web_url=r["web_url"],
                asterisk_host=r["asterisk_host"],
                vici_user=r["vici_user"],
                vici_pass=vp,
                phone_login=r["phone_login"],
                phone_pass=pp,
                campaign_id=r["campaign_id"],
                allowed_transfer_ingroups=list(r["allowed_transfer_ingroups"] or []),
            ))
        return out
