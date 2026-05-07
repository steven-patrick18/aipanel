"""Load SIP accounts from Postgres, register them in PJSIP, react to changes.

Account lifecycle
-----------------

* On startup: ``load_initial()`` reads every deployment in
  ``status IN ('starting', 'running')`` and schedules each to register
  with a staggered delay (uniform over ``register_stagger_sec`` ± jitter)
  to avoid REGISTER storms against Asterisk.
* On registration failure: PJSIP's auto-retry is disabled
  (``regRetryIntervalSec=0``). Our ``onRegState`` handler retries with
  exponential backoff (``register_backoff_sec``, default 5/10/30/60).
* On Redis pubsub message ``sip:accounts:changed``: ``add`` /
  ``update`` / ``remove`` actions run live.

Threading
---------

PJSIP callbacks fire on PJSIP threads. We always call
``endpoint.register_thread()`` from any Python thread before invoking
``setRegistration`` or ``create``.
"""

from __future__ import annotations

import json
import random
import threading
import time
from typing import TYPE_CHECKING, Callable
from uuid import UUID

import psycopg
import redis
import structlog
from cryptography.fernet import Fernet, InvalidToken

try:
    import pjsua2 as pj
except ImportError:                                          # pragma: no cover
    pj = None  # type: ignore[assignment]

from .config import SipConfig
from .models import SipAccountModel

if TYPE_CHECKING:                                            # pragma: no cover
    from .endpoint import SipEndpoint

log = structlog.get_logger().bind(component="account_manager")

# Channel name for live add/remove notifications.
PUBSUB_CHANNEL = "sip:accounts:changed"


SQL_LOAD_ACCOUNTS = """
    SELECT d.id::text          AS deployment_id,
           d.phone_login        AS phone_login,
           d.phone_pass_encrypted AS phone_pass_encrypted,
           v.asterisk_host      AS asterisk_host,
           v.asterisk_port      AS asterisk_port
      FROM deployments d
      JOIN vicidial_servers v ON d.vicidial_server_id = v.id
     WHERE d.status IN ('starting', 'running')
"""

SQL_LOAD_ONE = SQL_LOAD_ACCOUNTS + " AND d.id = %s"


# ---------------------------------------------------------------------------
# Per-account PJSIP wrapper
# ---------------------------------------------------------------------------

if pj is not None:

    class _PjAccount(pj.Account):                            # type: ignore[misc]
        """pjsua2 Account subclass with our reg-state retry + incoming-call hook."""

        def __init__(
            self,
            manager: "AccountManager",
            model: SipAccountModel,
        ) -> None:
            super().__init__()
            self._manager = manager
            self.model = model
            self._retry_idx = 0
            self._retry_timer: threading.Timer | None = None

        # --- PJSIP callbacks ---

        def onRegState(self, prm) -> None:                   # noqa: N802
            try:
                info = self.getInfo()
            except pj.Error as exc:                          # pragma: no cover
                log.warning("regstate_getinfo_failed",
                            account=str(self.model), error=str(exc))
                return

            if info.regIsActive:
                log.info("register_ok", account=str(self.model))
                self._retry_idx = 0
                self._manager._on_reg_success(self)
            else:
                log.warning("register_failed",
                            account=str(self.model),
                            reg_status=info.regStatus,
                            reg_status_text=info.regStatusText)
                self._manager._on_reg_failure(self)
                self._schedule_retry()

        def onIncomingCall(self, prm) -> None:               # noqa: N802
            self._manager.on_incoming_call(self, prm)

        # --- retry plumbing ---

        def _schedule_retry(self) -> None:
            delays = self._manager.cfg.register_backoff_sec
            delay = delays[min(self._retry_idx, len(delays) - 1)]
            self._retry_idx += 1
            log.info("register_retry_scheduled",
                     account=str(self.model), in_sec=delay,
                     attempt=self._retry_idx)
            timer = threading.Timer(delay, self._do_retry)
            timer.daemon = True
            timer.name = f"sip-reg-retry-{self.model.deployment_id}"
            self._retry_timer = timer
            timer.start()

        def _do_retry(self) -> None:
            self._manager.endpoint.register_thread(
                f"reg-retry-{self.model.deployment_id}")
            try:
                self.setRegistration(True)
            except pj.Error as exc:
                log.error("register_retry_failed",
                          account=str(self.model), error=str(exc))
                self._schedule_retry()


# ---------------------------------------------------------------------------
# AccountManager
# ---------------------------------------------------------------------------

OnIncomingCall = Callable[["object", "object"], None]
"""(account, OnIncomingCallParam) — wired to call_handler.handle_invite."""


class AccountManager:
    def __init__(
        self,
        endpoint: "SipEndpoint",
        cfg: SipConfig,
        db_dsn: str,
        redis_client: redis.Redis,
        on_incoming_call: OnIncomingCall,
        on_reg_success: Callable[[], None] | None = None,
        on_reg_failure: Callable[[], None] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.cfg = cfg
        self._db_dsn = db_dsn
        self._redis = redis_client
        self.on_incoming_call = on_incoming_call
        self._on_reg_success_cb = on_reg_success or (lambda: None)
        self._on_reg_failure_cb = on_reg_failure or (lambda: None)

        self._fernet = Fernet(cfg.encryption_key.encode("ascii"))
        self._accounts: dict[UUID, "object"] = {}
        self._accounts_lock = threading.Lock()
        self._pubsub_thread: threading.Thread | None = None
        self._stopped = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_initial(self) -> None:
        """Pull every active deployment, then schedule staggered registration."""
        models = self._fetch_models()
        log.info("accounts_loaded", count=len(models))

        if not models:
            return

        n = len(models)
        spread = self.cfg.register_stagger_sec
        jitter = self.cfg.register_jitter_sec

        for i, m in enumerate(models):
            base = (i / max(1, n)) * spread
            delay = max(0.0, min(spread, base + random.uniform(-jitter, jitter)))
            t = threading.Timer(delay, self._create_account, args=(m,))
            t.daemon = True
            t.name = f"sip-reg-init-{m.deployment_id}"
            t.start()

    def start_pubsub_watcher(self) -> None:
        """Subscribe to ``sip:accounts:changed`` in a background thread."""
        if self._pubsub_thread is not None:
            return
        t = threading.Thread(
            target=self._pubsub_loop, name="sip-pubsub", daemon=True
        )
        self._pubsub_thread = t
        t.start()

    def unregister_all(self) -> None:
        """Send REGISTER expires=0 for every account. Best-effort."""
        with self._accounts_lock:
            accounts = list(self._accounts.values())
        for acc in accounts:
            try:
                self.endpoint.register_thread("sip-shutdown")
                acc.setRegistration(False)
            except Exception as exc:                         # pragma: no cover
                log.warning("unregister_failed", error=str(exc))

    def stop(self) -> None:
        self._stopped.set()

    # ------------------------------------------------------------------
    # Internal — used by _PjAccount callbacks
    # ------------------------------------------------------------------

    def _on_reg_success(self, _acc) -> None:
        self._on_reg_success_cb()

    def _on_reg_failure(self, _acc) -> None:
        self._on_reg_failure_cb()

    # ------------------------------------------------------------------
    # Internal — DB + crypto
    # ------------------------------------------------------------------

    def _fetch_models(self, deployment_id: UUID | None = None) -> list[SipAccountModel]:
        sql = SQL_LOAD_ONE if deployment_id is not None else SQL_LOAD_ACCOUNTS
        params: tuple = (str(deployment_id),) if deployment_id is not None else ()
        try:
            with psycopg.connect(self._db_dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall()
                    cols = [d.name for d in cur.description]
        except psycopg.Error as exc:
            log.error("db_fetch_failed", error=str(exc))
            return []

        out: list[SipAccountModel] = []
        for row in rows:
            r = dict(zip(cols, row))
            try:
                phone_pass = self._fernet.decrypt(
                    r["phone_pass_encrypted"].encode("ascii")
                ).decode("utf-8")
            except (InvalidToken, ValueError, AttributeError):
                log.error("phone_pass_decrypt_failed",
                          deployment_id=r["deployment_id"])
                continue
            out.append(
                SipAccountModel(
                    deployment_id=UUID(r["deployment_id"]),
                    phone_login=r["phone_login"],
                    phone_pass=phone_pass,
                    asterisk_host=r["asterisk_host"],
                    asterisk_port=r["asterisk_port"],
                )
            )
        return out

    # ------------------------------------------------------------------
    # Internal — PJSIP account create / destroy
    # ------------------------------------------------------------------

    def _create_account(self, model: SipAccountModel) -> None:
        if pj is None:                                       # pragma: no cover
            log.error("pjsua2_unavailable")
            return
        with self._accounts_lock:
            if model.deployment_id in self._accounts:
                log.debug("account_already_present",
                          deployment_id=str(model.deployment_id))
                return

        self.endpoint.register_thread(f"sip-reg-{model.deployment_id}")

        acfg = pj.AccountConfig()
        acfg.idUri = f"sip:{model.phone_login}@{model.asterisk_host}"
        acfg.regConfig.registrarUri = (
            f"sip:{model.asterisk_host}:{model.asterisk_port}"
        )
        acfg.regConfig.timeoutSec       = 300
        acfg.regConfig.retryIntervalSec = 0      # we own retry
        acfg.regConfig.firstRetryIntervalSec = 0

        cred = pj.AuthCredInfo(
            "digest", "*", model.phone_login, 0, model.phone_pass
        )
        acfg.sipConfig.authCreds.append(cred)

        try:
            account = _PjAccount(self, model)
            account.create(acfg)
        except pj.Error as exc:
            log.error("account_create_failed",
                      account=str(model), error=str(exc))
            return

        with self._accounts_lock:
            self._accounts[model.deployment_id] = account
        log.info("account_created", account=str(model))

    def _destroy_account(self, deployment_id: UUID) -> None:
        with self._accounts_lock:
            account = self._accounts.pop(deployment_id, None)
        if account is None:
            return
        try:
            self.endpoint.register_thread(f"sip-del-{deployment_id}")
            account.shutdown()
        except Exception as exc:                             # pragma: no cover
            log.warning("account_shutdown_failed",
                        deployment_id=str(deployment_id), error=str(exc))
        log.info("account_destroyed", deployment_id=str(deployment_id))

    # ------------------------------------------------------------------
    # Internal — Redis pubsub
    # ------------------------------------------------------------------

    def _pubsub_loop(self) -> None:
        backoff = 1.0
        while not self._stopped.is_set():
            try:
                pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
                pubsub.subscribe(PUBSUB_CHANNEL)
                log.info("pubsub_subscribed", channel=PUBSUB_CHANNEL)
                backoff = 1.0
                for msg in pubsub.listen():
                    if self._stopped.is_set():
                        break
                    if msg is None or msg.get("type") != "message":
                        continue
                    self._handle_pubsub_message(msg.get("data"))
            except (redis.RedisError, OSError) as exc:
                log.warning("pubsub_disconnected",
                            error=str(exc), reconnect_in=backoff)
                if self._stopped.wait(timeout=backoff):
                    return
                backoff = min(backoff * 2, 30.0)

    def _handle_pubsub_message(self, raw: bytes | str | None) -> None:
        if raw is None:
            return
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
            action = data["action"]
            deployment_id = UUID(data["deployment_id"])
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            log.warning("pubsub_message_invalid", error=str(exc), raw=raw)
            return

        log.info("pubsub_action", action=action, deployment_id=str(deployment_id))
        if action == "remove":
            self._destroy_account(deployment_id)
        elif action in ("add", "update"):
            # Update = destroy then re-create with fresh DB row.
            if action == "update":
                self._destroy_account(deployment_id)
            models = self._fetch_models(deployment_id)
            for m in models:
                self._create_account(m)
        else:
            log.warning("pubsub_unknown_action", action=action)
