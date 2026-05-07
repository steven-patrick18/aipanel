"""Agent CRUD + custom actions."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models.agents import Agent
from ..schemas.agent import AgentCreate, AgentUpdate
from ..schemas.common import PaginationParams


async def list_agents(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    pagination: PaginationParams,
    name_contains: str | None = None,
    status_filter: str | None = None,
) -> tuple[list[Agent], int]:
    base = select(Agent).where(Agent.tenant_id == tenant_id)
    if name_contains:
        base = base.where(Agent.name.ilike(f"%{name_contains}%"))
    if status_filter:
        base = base.where(Agent.status == status_filter)

    total = (await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()

    rows = (await session.execute(
        base.order_by(Agent.updated_at.desc())
            .limit(pagination.limit)
            .offset(pagination.offset)
    )).scalars().all()
    return list(rows), int(total)


async def get_agent(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID,
) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="agent not found")
    return agent


async def create_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    payload: AgentCreate,
) -> Agent:
    agent = Agent(
        tenant_id=tenant_id,
        name=payload.name,
        persona=payload.persona.model_dump(),
        script=payload.script.model_dump(),
        scenario_tree=payload.scenario_tree.model_dump(),
        voice_id=payload.voice_id,
        language=payload.language,
        kb_collection_id=payload.kb_collection_id,
        status="draft",
    )
    session.add(agent)
    await session.flush()
    await session.refresh(agent)
    return agent


async def update_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    payload: AgentUpdate,
) -> Agent:
    agent = await get_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    data = payload.model_dump(exclude_unset=True)
    if "persona" in data and payload.persona is not None:
        agent.persona = payload.persona.model_dump()
    if "script" in data and payload.script is not None:
        agent.script = payload.script.model_dump()
    if "scenario_tree" in data and payload.scenario_tree is not None:
        agent.scenario_tree = payload.scenario_tree.model_dump()
    for field in ("name", "voice_id", "language", "kb_collection_id"):
        if field in data and data[field] is not None:
            setattr(agent, field, data[field])
    await session.flush()
    await session.refresh(agent)
    return agent


async def archive_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
) -> Agent:
    """Soft-delete: status='archived', row stays for audit trail."""
    agent = await get_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    agent.status = "archived"
    await session.flush()
    return agent


async def duplicate_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
) -> Agent:
    src = await get_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    dup = Agent(
        tenant_id=tenant_id,
        name=f"{src.name} (copy)",
        persona=dict(src.persona or {}),
        voice_id=src.voice_id,
        language=src.language,
        script=dict(src.script or {}),
        scenario_tree=dict(src.scenario_tree or {}),
        kb_collection_id=src.kb_collection_id,
        status="draft",
    )
    session.add(dup)
    await session.flush()
    await session.refresh(dup)
    return dup


async def promote_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
) -> Agent:
    agent = await get_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    agent.status = "ready"
    await session.flush()
    return agent
