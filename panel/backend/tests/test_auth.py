"""Auth flow: login → me → refresh → 401 on bad token."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_login_then_me(client, make_user):
    _, user, password = await make_user(role="admin", email="admin@test.local")

    r = await client.post("/api/v1/auth/login",
                          json={"email": user.email, "password": password})
    assert r.status_code == 200
    data = r.json()
    assert data["user"]["email"] == user.email
    access = data["tokens"]["access_token"]

    r = await client.get("/api/v1/auth/me",
                         headers={"Authorization": f"Bearer {access}"})
    assert r.status_code == 200
    assert r.json()["email"] == user.email
    assert r.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_login_bad_password(client, make_user):
    _, user, _ = await make_user(role="operator", email="op@test.local")
    r = await client.post("/api/v1/auth/login",
                          json={"email": user.email, "password": "wrong"})
    assert r.status_code == 401
    assert "invalid credentials" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_unknown_email(client):
    r = await client.post("/api/v1/auth/login",
                          json={"email": "ghost@test.local", "password": "x"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_without_token(client):
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_refresh_round_trip(client, make_user):
    _, user, password = await make_user(role="viewer", email="v@test.local")
    r = await client.post("/api/v1/auth/login",
                          json={"email": user.email, "password": password})
    refresh = r.json()["tokens"]["refresh_token"]

    r2 = await client.post("/api/v1/auth/refresh",
                           json={"refresh_token": refresh})
    assert r2.status_code == 200
    assert r2.json()["access_token"]
    assert r2.json()["refresh_token"]


@pytest.mark.asyncio
async def test_refresh_with_access_token_rejected(client, make_user):
    """Access tokens shouldn't be accepted as refresh."""
    _, user, password = await make_user(email="x@test.local")
    r = await client.post("/api/v1/auth/login",
                          json={"email": user.email, "password": password})
    access = r.json()["tokens"]["access_token"]

    r2 = await client.post("/api/v1/auth/refresh",
                           json={"refresh_token": access})
    assert r2.status_code == 401
