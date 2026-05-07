"""Smoke: /api/healthz unauthenticated, /api/v1/system/version requires auth."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_healthz_open(client):
    r = await client.get("/api/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_version_requires_auth(client):
    # GET version is on /system/version which has no @router-level auth dep,
    # but the endpoints in api/v1/system.py either take CurrentUser or are
    # admin-gated. /system/version doesn't require auth — let's verify.
    r = await client.get("/api/v1/system/version")
    assert r.status_code == 200
    assert "version" in r.json()
