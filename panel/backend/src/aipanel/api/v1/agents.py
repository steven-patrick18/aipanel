"""Agent CRUD + custom actions."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.deps import CurrentUser, TenantId
from ...auth.permissions import require_writer
from ...config import get_config
from ...db.models.vici import Deployment
from ...db.session import get_session
from ...integrations.session_mgr_client import SessionMgrClient
from ...schemas.agent import (
    AgentCreate,
    AgentRead,
    AgentTestCallRequest,
    AgentUpdate,
    TrainingExampleCreate,
    TrainingExampleRead,
)
from ...schemas.common import OkResponse, Page, PaginationParams
from ...services import agents_service
from ...services.audit_service import log_audit

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=Page[AgentRead])
async def list_agents(
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    name_contains: str | None = Query(None, max_length=200),
    status_filter: str | None = Query(None, alias="status"),
) -> Page[AgentRead]:
    items, total = await agents_service.list_agents(
        session, tenant_id=tenant_id,
        pagination=PaginationParams(limit=limit, offset=offset),
        name_contains=name_contains,
        status_filter=status_filter,
    )
    return Page(items=[AgentRead.model_validate(a) for a in items],
                total=total, limit=limit, offset=offset)


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(
    agent_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
) -> AgentRead:
    a = await agents_service.get_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    return AgentRead.model_validate(a)


@router.post("", response_model=AgentRead, status_code=201,
             dependencies=[Depends(require_writer)])
async def create_agent(
    body: AgentCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> AgentRead:
    a = await agents_service.create_agent(
        session, tenant_id=user.tenant_id, payload=body
    )
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="agent.create", target_type="agent",
                    target_id=a.id, payload={"name": a.name})
    return AgentRead.model_validate(a)


@router.patch("/{agent_id}", response_model=AgentRead,
              dependencies=[Depends(require_writer)])
async def update_agent(
    agent_id: UUID,
    body: AgentUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> AgentRead:
    a = await agents_service.update_agent(
        session, tenant_id=user.tenant_id, agent_id=agent_id, payload=body,
    )
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="agent.update", target_type="agent", target_id=a.id,
                    payload=body.model_dump(exclude_unset=True))
    return AgentRead.model_validate(a)


@router.delete("/{agent_id}", response_model=OkResponse,
               dependencies=[Depends(require_writer)])
async def archive_agent(
    agent_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> OkResponse:
    a = await agents_service.archive_agent(
        session, tenant_id=user.tenant_id, agent_id=agent_id,
    )
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="agent.archive", target_type="agent", target_id=a.id)
    return OkResponse()


@router.post("/{agent_id}/duplicate", response_model=AgentRead, status_code=201,
             dependencies=[Depends(require_writer)])
async def duplicate_agent(
    agent_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> AgentRead:
    a = await agents_service.duplicate_agent(
        session, tenant_id=user.tenant_id, agent_id=agent_id,
    )
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="agent.duplicate", target_type="agent", target_id=a.id,
                    payload={"source_id": str(agent_id)})
    return AgentRead.model_validate(a)


@router.post("/{agent_id}/promote", response_model=AgentRead,
             dependencies=[Depends(require_writer)])
async def promote_agent(
    agent_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> AgentRead:
    a = await agents_service.promote_agent(
        session, tenant_id=user.tenant_id, agent_id=agent_id,
    )
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="agent.promote", target_type="agent", target_id=a.id)
    return AgentRead.model_validate(a)


@router.post("/{agent_id}/test-call", response_model=OkResponse,
             dependencies=[Depends(require_writer)])
async def test_call(
    agent_id: UUID,
    body: AgentTestCallRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> OkResponse:
    """Originate a test call against this agent.

    Picks a running deployment for the agent (or the explicit
    ``deployment_id`` if supplied) and asks the Session Manager to do a
    ViciDial ``manual_dial`` of the supplied phone number. The dialler
    then bridges the resulting leg into the worker just like an inbound
    call, which is what gives the operator a live test of the agent.
    """
    # Verify the agent exists / is owned by this tenant.
    await agents_service.get_agent(
        session, tenant_id=user.tenant_id, agent_id=agent_id,
    )

    if body.deployment_id is not None:
        deployment = (await session.execute(
            select(Deployment).where(
                Deployment.id == body.deployment_id,
                Deployment.tenant_id == user.tenant_id,
                Deployment.agent_id == agent_id,
            )
        )).scalar_one_or_none()
        if deployment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="deployment not found for this agent",
            )
    else:
        deployment = (await session.execute(
            select(Deployment)
            .where(
                Deployment.tenant_id == user.tenant_id,
                Deployment.agent_id == agent_id,
                Deployment.status.in_(["running", "ready", "paused"]),
            )
            .order_by(Deployment.updated_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if deployment is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="no running deployment for this agent — start one first",
            )

    cfg = get_config()
    import os
    token = os.environ.get("SESSION_MGR_TOKEN", "")
    base = cfg.vici.url or "http://127.0.0.1:8010"
    async with SessionMgrClient(base, token, timeout_sec=10.0) as sm:
        ok, detail = await sm.manual_dial(
            str(deployment.id), body.phone_number,
        )
    if not ok:
        await log_audit(
            session, user_id=user.id, tenant_id=user.tenant_id,
            action="agent.test_call_failed", target_type="agent",
            target_id=agent_id,
            payload={"phone_number": body.phone_number,
                     "deployment_id": str(deployment.id),
                     "error": detail},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"session manager rejected dial: {detail}",
        )

    await log_audit(
        session, user_id=user.id, tenant_id=user.tenant_id,
        action="agent.test_call", target_type="agent",
        target_id=agent_id,
        payload={"phone_number": body.phone_number,
                 "deployment_id": str(deployment.id)},
    )
    return OkResponse()


@router.get("/{agent_id}/versions", response_model=list[dict])
async def list_versions(
    agent_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
) -> list[dict]:
    """Stub: full version history needs a dedicated agent_versions table."""
    await agents_service.get_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    return []


# ---------------------------------------------------------------------------
# Training examples — operator-curated few-shot examples per agent.
# These ride into the LLM prompt alongside the campaign few-shot pool;
# operators add them by typing pairs directly OR by marking a successful
# call as exemplary on the call detail page.
# ---------------------------------------------------------------------------


@router.get("/{agent_id}/training-examples",
            response_model=list[TrainingExampleRead])
async def list_training_examples(
    agent_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
) -> list[TrainingExampleRead]:
    a = await agents_service.get_agent(
        session, tenant_id=tenant_id, agent_id=agent_id,
    )
    return [TrainingExampleRead.model_validate(x) for x in (a.training_examples or [])]


@router.post("/{agent_id}/training-examples",
             response_model=TrainingExampleRead, status_code=201,
             dependencies=[Depends(require_writer)])
async def add_training_example(
    agent_id: UUID,
    body: TrainingExampleCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> TrainingExampleRead:
    from datetime import datetime, timezone
    from uuid import uuid4

    a = await agents_service.get_agent(
        session, tenant_id=user.tenant_id, agent_id=agent_id,
    )
    entry = {
        "id": str(uuid4()),
        "kind": "manual",
        "user": body.user,
        "agent": body.agent,
        "notes": body.notes,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "added_by": str(user.id),
    }
    a.training_examples = [*(a.training_examples or []), entry]
    await session.flush()
    await log_audit(
        session, user_id=user.id, tenant_id=user.tenant_id,
        action="agent.training_example_add", target_type="agent",
        target_id=agent_id, payload={"kind": "manual"},
    )
    return TrainingExampleRead.model_validate(entry)


@router.delete("/{agent_id}/training-examples/{example_id}",
               response_model=OkResponse,
               dependencies=[Depends(require_writer)])
async def delete_training_example(
    agent_id: UUID,
    example_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> OkResponse:
    a = await agents_service.get_agent(
        session, tenant_id=user.tenant_id, agent_id=agent_id,
    )
    before = len(a.training_examples or [])
    a.training_examples = [
        x for x in (a.training_examples or []) if x.get("id") != example_id
    ]
    if len(a.training_examples) == before:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="training example not found",
        )
    await session.flush()
    await log_audit(
        session, user_id=user.id, tenant_id=user.tenant_id,
        action="agent.training_example_delete", target_type="agent",
        target_id=agent_id, payload={"example_id": example_id},
    )
    return OkResponse()
