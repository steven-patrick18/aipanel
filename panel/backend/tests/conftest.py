"""Shared test fixtures.

Tests use SQLite in-memory + a stubbed Redis/ARQ. The aipanel config is
swapped out with a tiny in-process loader so we don't need /etc/aipanel.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


# ---------------------------------------------------------------------------
# Environment + config patching MUST happen before any aipanel import.
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("AIPANEL_CONF", str(Path(__file__).resolve().parent / "test.conf"))
os.environ.setdefault("AIPANEL_SECRETS", "")
os.environ["DB_PASSWORD"]      = "test"
os.environ["JWT_SECRET"]       = "test-secret-please-change"
os.environ["ENCRYPTION_KEY"]   = "0123456789abcdef0123456789abcdef0123456789ab=="
os.environ["MINIO_ACCESS_KEY"] = "test"
os.environ["MINIO_SECRET_KEY"] = "test"

# Build a minimal aipanel.conf for the loader to parse.
_TEST_CONF_PATH = Path(os.environ["AIPANEL_CONF"])
_TEST_CONF_PATH.write_text("""
[database]
host = "127.0.0.1"
port = 5432
name = "aipanel_test"
user = "aipanel"

[redis]
host = "127.0.0.1"
port = 6379
db = 15

[minio]
endpoint = "127.0.0.1:9000"
console_endpoint = "127.0.0.1:9001"
secure = false
bucket_recordings = "x"
bucket_transcripts = "x"
bucket_kb = "x"
bucket_voices = "x"

[sip]
listen_host = "127.0.0.1"
listen_port = 5060
public_ip = "127.0.0.1"

[llm]
provider = "vllm"
endpoint = "http://127.0.0.1:8001/v1"
model = "test"

[stt]
provider = "whisper"
endpoint = "http://127.0.0.1:8002"
model = "test"

[tts]
provider = "noop"
endpoint = "http://127.0.0.1:8003"

[panel]
listen_host = "127.0.0.1"
listen_port = 8000
public_url = "http://127.0.0.1:8000"

[cluster]
node_role = "primary"
hostname = "test"
""", encoding="utf-8")


# ---------------------------------------------------------------------------
# DB / session swap — replace the postgres engine with SQLite.
#
# This isn't a full integration test of the SQL we generate (some queries use
# Postgres-only features like date_trunc / JSONB ops) — those tests need a
# real Postgres. The swap covers auth + simple CRUD round trips.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    from aipanel.db.base import Base
    import aipanel.db.models  # register models

    async with eng.begin() as conn:
        # SQLite can't do all our Postgres types — skip the partitioned
        # call_events + the BIGSERIAL audit_log + UUID gen. We just create
        # the tables it CAN handle for unit tests.
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture()
async def session(engine) -> AsyncIterator[AsyncSession]:
    sm = async_sessionmaker(bind=engine, class_=AsyncSession,
                            expire_on_commit=False)
    async with sm() as s:
        yield s


@pytest_asyncio.fixture()
async def client(engine) -> AsyncIterator[AsyncClient]:
    """ASGI test client. Wires the session dep to use the in-memory engine."""
    from aipanel import db as _dbmod
    from aipanel.db import session as _sess
    from aipanel.main import create_app

    app = create_app()

    sm = async_sessionmaker(bind=engine, class_=AsyncSession,
                            expire_on_commit=False)

    async def _override_session():
        async with sm() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[_sess.get_session] = _override_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def make_user(session):
    from aipanel.auth.jwt import hash_password
    from aipanel.db.models.tenants import Tenant, User

    async def _factory(role: str = "admin",
                       email: str | None = None,
                       password: str = "hunter22hunter22"):
        tenant = Tenant(name="Test")
        session.add(tenant)
        await session.flush()
        user = User(
            tenant_id=tenant.id,
            email=email or f"u-{uuid.uuid4().hex[:6]}@test.local",
            password_hash=hash_password(password),
            role=role,
        )
        session.add(user)
        await session.flush()
        await session.refresh(user)
        return tenant, user, password

    return _factory
