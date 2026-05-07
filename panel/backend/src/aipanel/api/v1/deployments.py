"""Deployments CRUD + start/stop/pause + live SSE."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, AsyncIterator
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.deps import CurrentUser, TenantId
from ...auth.permissions import require_writer
from ...config import get_config
from ...db.session import get_session
from ...events.publisher import deployment_channel
from ...events.sse import sse_response
from ...integrations.session_mgr_client import SessionMgrClient
from ...schemas.common import OkResponse, Page, PaginationParams
from ...schemas.deployment import (
    DeploymentCreate,
    DeploymentRead,
    DeploymentUpdate,
)
from ...services import deployment_service
from ...services.audit_service import log_audit

router = APIRouter(prefix="/deployments", tags=["deployments"])


@router.get("", response_model=Page[DeploymentRead])
async def list_deployments(
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
    limit: int = 50, offset: int = 0,
    status_filter: str | None = Query(None, alias="status"),
) -> Page[DeploymentRead]:
    items, total = await deployment_service.list_deployments(
        session, tenant_id=tenant_id,
        pagination=PaginationParams(limit=limit, offset=offset),
        status_filter=status_filter,
    )
    return Page(items=[DeploymentRead.model_validate(d) for d in items],
                total=total, limit=limit, offset=offset)


@router.get("/{deployment_id}", response_model=DeploymentRead)
async def get_deployment(
    deployment_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
) -> DeploymentRead:
    d = await deployment_service.get_deployment(
        session, tenant_id=tenant_id, deployment_id=deployment_id,
    )
    return DeploymentRead.model_validate(d)


@router.post("", response_model=DeploymentRead, status_code=201,
             dependencies=[Depends(require_writer)])
async def create_deployment(
    body: DeploymentCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> DeploymentRead:
    d = await deployment_service.create_deployment(
        session, tenant_id=user.tenant_id, payload=body,
    )
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="deployment.create", target_type="deployment",
                    target_id=d.id, payload={"agent_id": str(body.agent_id)})
    return DeploymentRead.model_validate(d)


@router.patch("/{deployment_id}", response_model=DeploymentRead,
              dependencies=[Depends(require_writer)])
async def update_deployment(
    deployment_id: UUID,
    body: DeploymentUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> DeploymentRead:
    d = await deployment_service.update_deployment(
        session, tenant_id=user.tenant_id,
        deployment_id=deployment_id, payload=body,
    )
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="deployment.update", target_type="deployment",
                    target_id=d.id,
                    payload=body.model_dump(exclude_unset=True,
                                             exclude={"vici_pass", "phone_pass"}))
    return DeploymentRead.model_validate(d)


@router.delete("/{deployment_id}", response_model=OkResponse,
               dependencies=[Depends(require_writer)])
async def delete_deployment(
    deployment_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> OkResponse:
    await deployment_service.delete_deployment(
        session, tenant_id=user.tenant_id, deployment_id=deployment_id,
    )
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="deployment.delete", target_type="deployment",
                    target_id=deployment_id)
    return OkResponse()


# ---------------------------------------------------------------------------
# Lifecycle controls — proxy to session-mgr
# ---------------------------------------------------------------------------

async def _session_mgr_client() -> SessionMgrClient:
    cfg = get_config()
    import os
    token = os.environ.get("SESSION_MGR_TOKEN", "")
    return SessionMgrClient(cfg.vici.url or "http://127.0.0.1:8010", token)


@router.post("/{deployment_id}/start", response_model=OkResponse,
             dependencies=[Depends(require_writer)])
async def start_deployment(
    deployment_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> OkResponse:
    d = await deployment_service.set_status(
        session, tenant_id=user.tenant_id,
        deployment_id=deployment_id, new_status="starting",
    )
    async with await _session_mgr_client() as sm:
        await sm.start(str(deployment_id))
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="deployment.start", target_type="deployment",
                    target_id=d.id)
    return OkResponse()


@router.post("/{deployment_id}/stop", response_model=OkResponse,
             dependencies=[Depends(require_writer)])
async def stop_deployment(
    deployment_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> OkResponse:
    d = await deployment_service.set_status(
        session, tenant_id=user.tenant_id,
        deployment_id=deployment_id, new_status="stopped",
    )
    async with await _session_mgr_client() as sm:
        await sm.stop(str(deployment_id))
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="deployment.stop", target_type="deployment",
                    target_id=d.id)
    return OkResponse()


@router.post("/{deployment_id}/pause", response_model=OkResponse,
             dependencies=[Depends(require_writer)])
async def pause_deployment(
    deployment_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
    pause_code: str = Query("BREAK", max_length=64),
) -> OkResponse:
    await deployment_service.get_deployment(
        session, tenant_id=user.tenant_id, deployment_id=deployment_id,
    )
    async with await _session_mgr_client() as sm:
        await sm.pause(str(deployment_id), pause_code)
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="deployment.pause", target_type="deployment",
                    target_id=deployment_id, payload={"pause_code": pause_code})
    return OkResponse()


# ---------------------------------------------------------------------------
# Live SSE
# ---------------------------------------------------------------------------

@router.get("/{deployment_id}/live")
async def live_stream(
    deployment_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
):
    # Authorise: deployment must belong to caller's tenant.
    await deployment_service.get_deployment(
        session, tenant_id=tenant_id, deployment_id=deployment_id,
    )
    cfg = get_config()
    redis_client = aioredis.from_url(cfg.redis.url, decode_responses=False)

    async def _event_source() -> AsyncIterator[dict]:
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(deployment_channel(deployment_id))
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                raw = msg.get("data")
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", "replace")
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    yield {"type": "raw", "data": raw}
        finally:
            try:
                await pubsub.unsubscribe()
                await pubsub.aclose()
            except Exception:
                pass
            await redis_client.aclose()

    return sse_response(request, _event_source())
