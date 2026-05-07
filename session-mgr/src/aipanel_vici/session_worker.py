"""Per-deployment session state machine.

Owns:
* The captured Playwright session
* The httpx ViciHttp instance
* All adapter-driven actions (heartbeat, dispose, transfer, etc.)
* The Redis mirror

Lifecycle::

    worker = SessionWorker(...)
    await worker.start()       # Playwright login, then ready
    # ...heartbeat + actions called from supervisor / API...
    await worker.stop()        # logout + cleanup
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis
import structlog

from .adapters.base import (
    AdapterError,
    HttpRequestSpec,
    SessionExpired,
    VicidialAdapter,
)
from .http_session import ViciHttp
from .login import BrowserPool, login_once
from .metrics import M_HEARTBEAT, M_LOGIN, M_SESSIONS
from .models import (
    CallInfo,
    CapturedSession,
    DeploymentRow,
    LeadData,
    SessionState,
    SessionStatus,
)

log = structlog.get_logger().bind(component="session_worker")


def _redis_key(deployment_id: str) -> str:
    return f"vici:session:{deployment_id}"


class SessionWorker:
    def __init__(
        self,
        deployment: DeploymentRow,
        adapter: VicidialAdapter,
        browser_pool: BrowserPool,
        redis_client: aioredis.Redis,
        login_backoff_sec: tuple[int, ...] = (5, 30, 120, 600),
        login_timeout_sec: float = 30.0,
        screenshot_dir: str | None = None,
    ) -> None:
        self.deployment = deployment
        self.adapter = adapter
        self.browser_pool = browser_pool
        self.redis = redis_client
        self.login_backoff_sec = login_backoff_sec
        self.login_timeout_sec = login_timeout_sec
        self.screenshot_dir = screenshot_dir

        self.state = SessionState(
            deployment_id=str(deployment.deployment_id),
            tenant_id=str(deployment.tenant_id),
            vici_user=deployment.vici_user,
            phone_login=deployment.phone_login,
            campaign=deployment.campaign_id,
        )
        self._captured: CapturedSession | None = None
        self._http: ViciHttp | None = None
        self._lock = asyncio.Lock()
        self._stopped = False

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Try Redis-cached cookies first, then Playwright."""
        await self._set_status(SessionStatus.LOGGING_IN)

        if await self._resume_from_redis():
            return
        await self._login_with_backoff()

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        log.info("session_stopping",
                 deployment_id=self.state.deployment_id)

        if self._captured is not None and self._http is not None:
            try:
                spec = self.adapter.logout_request(self._captured, self.deployment)
                await self._http.send(self.adapter, spec)
            except Exception as exc:                         # pragma: no cover
                log.warning("logout_request_failed", error=str(exc))
            try:
                await self._http.aclose()
            except Exception:                                # pragma: no cover
                pass
            self._http = None

        await self._set_status(SessionStatus.LOGGED_OUT)
        try:
            await self.redis.delete(_redis_key(self.state.deployment_id))
        except aioredis.RedisError:                          # pragma: no cover
            pass

    # ------------------------------------------------------------------
    # Heartbeat (called by heartbeat scheduler)
    # ------------------------------------------------------------------

    async def heartbeat(self) -> None:
        if self._captured is None or self._http is None:
            return
        spec = self.adapter.heartbeat_request(self._captured, self.deployment)
        try:
            status, body = await self._http.send(self.adapter, spec)
        except Exception as exc:                             # pragma: no cover
            M_HEARTBEAT.labels(result="fail").inc()
            log.warning("heartbeat_send_exc",
                        deployment_id=self.state.deployment_id,
                        error=str(exc))
            self.state.heartbeat_failures += 1
            await self._maybe_recover()
            return

        if self._http.detect_session_expired(self.adapter, status, body):
            M_HEARTBEAT.labels(result="fail").inc()
            log.warning("heartbeat_session_expired",
                        deployment_id=self.state.deployment_id, status=status)
            self.state.heartbeat_failures += 1
            await self._maybe_recover()
            return

        M_HEARTBEAT.labels(result="ok").inc()
        self.state.heartbeat_failures = 0
        self.state.last_heartbeat_at = time.time()
        await self._mirror_to_redis()

    # ------------------------------------------------------------------
    # Action helpers (called by api.py)
    # ------------------------------------------------------------------

    async def get_call_info(self) -> CallInfo:
        async with self._lock:
            spec = self.adapter.get_call_info_request(self._captured, self.deployment)
            status, body = await self._http.send(self.adapter, spec)
            self._raise_if_expired(status, body)
            info = self.adapter.parse_call_info_response(body)
            if info.lead_id:
                self.state.last_call_id = info.uniqueid or self.state.last_call_id
                await self._mirror_to_redis()
            return info

    async def get_lead(self, lead_id: str) -> LeadData:
        async with self._lock:
            spec = self.adapter.get_lead_request(self._captured, self.deployment, lead_id)
            status, body = await self._http.send(self.adapter, spec)
            # update_lead with admin auth doesn't share the agent session;
            # we don't treat 401 here as session-expired.
            return self.adapter.parse_lead_response(body, lead_id)

    async def dispose(
        self,
        status: str,
        callback_datetime: str | None = None,
        notes: str = "",
    ) -> None:
        async with self._lock:
            spec = self.adapter.dispose_request(
                self._captured, self.deployment,
                status, callback_datetime, notes,
            )
            sc, body = await self._http.send(self.adapter, spec)
            self._raise_if_expired(sc, body)

    async def transfer_conference(self, ingroup_id: str, summary: str) -> None:
        async with self._lock:
            spec = self.adapter.transfer_conference_request(
                self._captured, self.deployment, ingroup_id, summary
            )
            sc, body = await self._http.send(self.adapter, spec)
            self._raise_if_expired(sc, body)

    async def pause(self, pause_code: str) -> None:
        async with self._lock:
            spec = self.adapter.pause_request(
                self._captured, self.deployment, pause_code
            )
            sc, body = await self._http.send(self.adapter, spec)
            self._raise_if_expired(sc, body)
            await self._set_status(SessionStatus.PAUSED)

    async def resume(self) -> None:
        async with self._lock:
            spec = self.adapter.resume_request(self._captured, self.deployment)
            sc, body = await self._http.send(self.adapter, spec)
            self._raise_if_expired(sc, body)
            await self._set_status(SessionStatus.READY)

    async def hangup(self) -> None:
        async with self._lock:
            spec = self.adapter.hangup_request(self._captured, self.deployment)
            sc, body = await self._http.send(self.adapter, spec)
            self._raise_if_expired(sc, body)

    async def manual_dial(self, phone_number: str) -> None:
        """Originate an outbound call from this agent seat — used by /test-call."""
        async with self._lock:
            spec = self.adapter.manual_dial_request(
                self._captured, self.deployment, phone_number,
            )
            sc, body = await self._http.send(self.adapter, spec)
            self._raise_if_expired(sc, body)

    # ------------------------------------------------------------------
    # Login machinery
    # ------------------------------------------------------------------

    async def _login_with_backoff(self) -> None:
        """Run Playwright login with exponential backoff. Marks ERROR on terminal failure."""
        for delay in (0, *self.login_backoff_sec):
            if self._stopped:
                return
            if delay:
                log.info("login_backoff_wait",
                         deployment_id=self.state.deployment_id, sleep_sec=delay)
                await asyncio.sleep(delay)
            self.state.login_attempts += 1
            try:
                captured = await login_once(
                    self.browser_pool,
                    self.adapter,
                    self.deployment,
                    timeout_sec=self.login_timeout_sec,
                    screenshot_dir=self.screenshot_dir,
                )
            except (AdapterError, Exception) as exc:                # noqa: BLE001
                M_LOGIN.labels(result="fail").inc()
                self.state.last_error = str(exc)
                log.warning("login_failed",
                            deployment_id=self.state.deployment_id,
                            attempt=self.state.login_attempts,
                            error=str(exc))
                continue

            await self._adopt_captured(captured)
            return

        await self._set_status(SessionStatus.ERROR)
        log.error("login_terminally_failed",
                  deployment_id=self.state.deployment_id,
                  attempts=self.state.login_attempts)

    async def _resume_from_redis(self) -> bool:
        """Try to revive a session from cached cookies; verify with one heartbeat."""
        try:
            payload = await self.redis.hgetall(_redis_key(self.state.deployment_id))
        except aioredis.RedisError:
            return False
        if not payload:
            return False
        decoded = {
            (k.decode() if isinstance(k, bytes) else k):
            (v.decode() if isinstance(v, bytes) else v)
            for k, v in payload.items()
        }
        try:
            prior = SessionState.from_redis_payload(decoded)
        except Exception:                                    # pragma: no cover
            return False
        if not prior.cookies or not prior.conf_exten:
            return False

        captured = CapturedSession(
            cookies=prior.cookies,
            conf_exten=prior.conf_exten,
            session_id=prior.session_id,
            session_name=prior.session_name,
            user_agent=prior.user_agent,
        )
        await self._adopt_captured(captured)

        try:
            await self.heartbeat()
        except Exception:                                    # pragma: no cover
            log.info("redis_resume_heartbeat_failed",
                     deployment_id=self.state.deployment_id)
            return False
        if self.state.heartbeat_failures > 0:
            log.info("redis_resume_stale_cookies",
                     deployment_id=self.state.deployment_id)
            self._captured = None
            if self._http is not None:
                await self._http.aclose()
                self._http = None
            return False

        log.info("session_resumed_from_redis",
                 deployment_id=self.state.deployment_id)
        M_LOGIN.labels(result="ok").inc()
        return True

    async def _adopt_captured(self, captured: CapturedSession) -> None:
        self._captured = captured
        if self._http is not None:
            await self._http.aclose()
        self._http = ViciHttp(self.deployment, captured)

        self.state.cookies = dict(captured.cookies)
        self.state.conf_exten = captured.conf_exten
        self.state.session_id = captured.session_id
        self.state.session_name = captured.session_name
        self.state.user_agent = captured.user_agent
        self.state.last_heartbeat_at = time.time()
        self.state.heartbeat_failures = 0
        self.state.last_error = ""
        M_LOGIN.labels(result="ok").inc()
        await self._set_status(SessionStatus.READY)

    async def _maybe_recover(self) -> None:
        if self.state.heartbeat_failures < 3:
            return
        log.warning("session_recovery_relogin",
                    deployment_id=self.state.deployment_id)
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        self._captured = None
        await self._login_with_backoff()

    # ------------------------------------------------------------------
    # State + Redis mirror
    # ------------------------------------------------------------------

    async def _set_status(self, status: SessionStatus) -> None:
        prev = self.state.status
        self.state.status = status
        if prev != status:
            try:
                M_SESSIONS.labels(status=prev.value).dec()
            except Exception:                                # pragma: no cover
                pass
            try:
                M_SESSIONS.labels(status=status.value).inc()
            except Exception:                                # pragma: no cover
                pass
        await self._mirror_to_redis()

    async def _mirror_to_redis(self) -> None:
        try:
            payload = self.state.to_redis_payload()
            await self.redis.hset(_redis_key(self.state.deployment_id), mapping=payload)
            await self.redis.expire(_redis_key(self.state.deployment_id), 24 * 3600)
        except aioredis.RedisError:                          # pragma: no cover
            log.warning("redis_mirror_failed",
                        deployment_id=self.state.deployment_id)

    def _raise_if_expired(self, status: int, body: str) -> None:
        if self._http is None:
            raise SessionExpired("no http session")
        if self._http.detect_session_expired(self.adapter, status, body):
            self.state.heartbeat_failures += 99    # force re-login next tick
            raise SessionExpired(f"vici returned status={status}, body[:80]={body[:80]!r}")
