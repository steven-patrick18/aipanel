"""Tests for SessionWorker state transitions with mocked HTTP + Playwright.

These run without real Redis/Playwright/Postgres — every dependency is a
small in-process stub.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from aipanel_vici.adapters.v2_14 import ViciDialAdapter_2_14
from aipanel_vici.models import CapturedSession, DeploymentRow, SessionStatus
from aipanel_vici.session_worker import SessionWorker


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _RedisStub:
    """In-memory hash store implementing just the methods SessionWorker uses."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}

    async def hset(self, key: str, mapping: dict[str, str]) -> None:
        self.hashes.setdefault(key, {}).update(mapping)

    async def hgetall(self, key: str) -> dict[bytes, bytes]:
        h = self.hashes.get(key, {})
        return {k.encode(): v.encode() for k, v in h.items()}

    async def expire(self, key: str, _ttl: int) -> None:
        pass

    async def delete(self, key: str) -> None:
        self.hashes.pop(key, None)


class _BrowserPoolStub:
    """Returns a canned CapturedSession from acquire-and-release flow.

    The login flow doesn't actually go through this stub — we monkeypatch
    `session_worker.login_once` directly in the tests below.
    """
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def acquire(self): return None
    async def release(self, _ctx): ...


class _ViciHttpStub:
    """Replaces ViciHttp inside SessionWorker. Records sent specs + scripts replies."""

    def __init__(self) -> None:
        self.sent: list[Any] = []
        self.script: list[tuple[int, str]] = [(200, "OK8600099")]

    async def send(self, _adapter, spec):
        self.sent.append(spec)
        if self.script:
            return self.script.pop(0)
        return 200, "OK"

    def detect_session_expired(self, adapter, status: int, body: str) -> bool:
        return adapter.is_response_session_expired(body, status)

    async def aclose(self) -> None: ...


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _deployment() -> DeploymentRow:
    return DeploymentRow(
        deployment_id=uuid4(),
        tenant_id=uuid4(),
        vici_server_id=uuid4(),
        web_url="https://vici.example.com/",
        asterisk_host="vici.example.com",
        vici_user="agent01",
        vici_pass="secret",
        phone_login="9001",
        phone_pass="ppwd",
        campaign_id="CAMP",
    )


@pytest.fixture()
def captured() -> CapturedSession:
    return CapturedSession(
        cookies={"PHPSESSID": "abc123"},
        conf_exten="8600099",
        session_id="TOKENXYZ",
        session_name="agent01_2024",
    )


@pytest.fixture()
def worker(monkeypatch, captured) -> SessionWorker:
    """Build a SessionWorker whose login + http are stubbed."""
    redis = _RedisStub()

    async def _fake_login(*_a, **_kw):
        return captured

    monkeypatch.setattr(
        "aipanel_vici.session_worker.login_once", _fake_login,
    )
    monkeypatch.setattr(
        "aipanel_vici.session_worker.ViciHttp",
        lambda *a, **kw: _ViciHttpStub(),
    )

    return SessionWorker(
        deployment=_deployment(),
        adapter=ViciDialAdapter_2_14(),
        browser_pool=_BrowserPoolStub(),
        redis_client=redis,           # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# start() / readiness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_succeeds_marks_ready(worker):
    await worker.start()
    assert worker.state.status == SessionStatus.READY
    assert worker.state.conf_exten == "8600099"
    assert worker.state.heartbeat_failures == 0


@pytest.mark.asyncio
async def test_redis_mirror_after_start(worker):
    await worker.start()
    raw = worker.redis.hashes[f"vici:session:{worker.state.deployment_id}"]
    assert raw["status"] == "ready"
    assert raw["conf_exten"] == "8600099"


# ---------------------------------------------------------------------------
# Heartbeat behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_heartbeat_success_resets_failures(worker, monkeypatch):
    await worker.start()
    worker.state.heartbeat_failures = 2
    # Default ViciHttpStub script returns (200, "OK8600099") — not expired.
    await worker.heartbeat()
    assert worker.state.heartbeat_failures == 0
    assert worker.state.last_heartbeat_at is not None


@pytest.mark.asyncio
async def test_heartbeat_session_expired_triggers_recovery(worker, monkeypatch, captured):
    await worker.start()

    # Make the next 3 heartbeats look like a logged-out session.
    worker._http.script = [(200, "NOT LOGGED-IN")] * 3

    # Capture re-login attempts.
    relogin_calls = {"n": 0}

    async def _fake_relogin(*_a, **_kw):
        relogin_calls["n"] += 1
        return captured

    monkeypatch.setattr(
        "aipanel_vici.session_worker.login_once", _fake_relogin,
    )

    for _ in range(3):
        await worker.heartbeat()
    # 3 strikes in heartbeat() then _maybe_recover triggers Playwright again.
    assert relogin_calls["n"] >= 1


# ---------------------------------------------------------------------------
# Redis-resume path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_from_redis_skips_playwright(monkeypatch, captured):
    redis = _RedisStub()
    deployment = _deployment()
    key = f"vici:session:{deployment.deployment_id}"

    # Pre-populate Redis as if a previous run had a healthy session.
    redis.hashes[key] = {
        "deployment_id": str(deployment.deployment_id),
        "tenant_id": str(deployment.tenant_id),
        "vici_user": deployment.vici_user,
        "phone_login": deployment.phone_login,
        "campaign": deployment.campaign_id,
        "status": "ready",
        "cookies": '{"PHPSESSID": "abc123"}',
        "conf_exten": "8600099",
        "session_id": "TOKENXYZ",
        "session_name": "agent01_2024",
        "user_agent": "ua",
        "last_heartbeat_at": "1700000000",
        "login_attempts": "0",
        "heartbeat_failures": "0",
        "last_error": "",
        "created_at": "1700000000",
    }

    login_called = {"n": 0}

    async def _no_playwright(*_a, **_kw):
        login_called["n"] += 1
        return captured

    monkeypatch.setattr(
        "aipanel_vici.session_worker.login_once", _no_playwright,
    )
    monkeypatch.setattr(
        "aipanel_vici.session_worker.ViciHttp",
        lambda *a, **kw: _ViciHttpStub(),
    )

    worker = SessionWorker(
        deployment=deployment,
        adapter=ViciDialAdapter_2_14(),
        browser_pool=_BrowserPoolStub(),
        redis_client=redis,           # type: ignore[arg-type]
    )
    await worker.start()
    assert login_called["n"] == 0
    assert worker.state.status == SessionStatus.READY


# ---------------------------------------------------------------------------
# Disposition action ends up calling the right endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispose_calls_user_dispo_log(worker):
    await worker.start()
    await worker.dispose("QUAL", notes="ready to buy")
    sent = worker._http.sent
    assert sent, "dispose did not send any HTTP request"
    spec = sent[-1]
    assert spec.path == "/agc/vdc_db_query.php"
    assert spec.data["function"] == "user_dispo_log"
    assert spec.data["status"] == "QUAL"
