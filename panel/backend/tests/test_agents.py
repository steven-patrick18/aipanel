"""Agents: CRUD + permissions."""

from __future__ import annotations

import pytest


def _agent_payload(name: str = "Sam") -> dict:
    return {
        "name": name,
        "persona": {
            "name": name,
            "age_range": "30-40",
            "gender": "neutral",
            "accent": "neutral",
            "backstory": "An outreach specialist.",
        },
        "script": {
            "opening_variants": ["Hi, this is Sam.", "Hello, Sam here."],
            "sections": [
                {"id": "s1", "title": "Intro",
                 "content": "Quick intro.", "expected_response_keywords": []},
            ],
            "closing": "Thanks.",
            "objections": [],
        },
        "scenario_tree": {"rules": []},
        "language": "en",
    }


async def _login(client, user_email, password) -> str:
    r = await client.post("/api/v1/auth/login",
                          json={"email": user_email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["tokens"]["access_token"]


@pytest.mark.asyncio
async def test_create_list_get_agent_as_operator(client, make_user):
    _, user, password = await make_user(role="operator", email="op@test.local")
    token = await _login(client, user.email, password)
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post("/api/v1/agents",
                          json=_agent_payload(), headers=headers)
    assert r.status_code == 201, r.text
    agent_id = r.json()["id"]

    r = await client.get("/api/v1/agents", headers=headers)
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["id"] == agent_id

    r = await client.get(f"/api/v1/agents/{agent_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["name"] == "Sam"
    assert r.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_viewer_cannot_create(client, make_user):
    _, user, password = await make_user(role="viewer", email="v@test.local")
    token = await _login(client, user.email, password)
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post("/api/v1/agents",
                          json=_agent_payload(), headers=headers)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_archive_then_status_archived(client, make_user):
    _, user, password = await make_user(role="admin", email="a@test.local")
    token = await _login(client, user.email, password)
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post("/api/v1/agents",
                          json=_agent_payload(), headers=headers)
    aid = r.json()["id"]

    r = await client.delete(f"/api/v1/agents/{aid}", headers=headers)
    assert r.status_code == 200

    r = await client.get(f"/api/v1/agents/{aid}", headers=headers)
    assert r.json()["status"] == "archived"


@pytest.mark.asyncio
async def test_duplicate_clones_payload(client, make_user):
    _, user, password = await make_user(role="admin", email="b@test.local")
    token = await _login(client, user.email, password)
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post("/api/v1/agents",
                          json=_agent_payload("Original"), headers=headers)
    src_id = r.json()["id"]

    r = await client.post(f"/api/v1/agents/{src_id}/duplicate", headers=headers)
    assert r.status_code == 201
    dup = r.json()
    assert dup["id"] != src_id
    assert dup["name"].startswith("Original")


@pytest.mark.asyncio
async def test_invalid_persona_rejected(client, make_user):
    _, user, password = await make_user(role="admin", email="c@test.local")
    token = await _login(client, user.email, password)
    headers = {"Authorization": f"Bearer {token}"}

    bad = _agent_payload()
    bad["persona"]["age_range"] = "very-old"   # not in Literal
    r = await client.post("/api/v1/agents", json=bad, headers=headers)
    assert r.status_code == 422
