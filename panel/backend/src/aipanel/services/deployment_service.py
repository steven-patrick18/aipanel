"""Deployment CRUD + start/stop bridge to the Session Manager."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..crypto import encrypt
from ..db.models.vici import Deployment
from ..schemas.common import PaginationParams
from ..schemas.deployment import DeploymentCreate, DeploymentUpdate


async def list_deployments(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    pagination: PaginationParams,
    status_filter: str | None = None,
) -> tuple[list[Deployment], int]:
    base = select(Deployment).where(Deployment.tenant_id == tenant_id)
    if status_filter:
        base = base.where(Deployment.status == status_filter)
    total = (await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()
    rows = (await session.execute(
        base.order_by(Deployment.updated_at.desc())
            .limit(pagination.limit)
            .offset(pagination.offset)
    )).scalars().all()
    return list(rows), int(total)


async def get_deployment(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    deployment_id: UUID,
) -> Deployment:
    d = await session.get(Deployment, deployment_id)
    if d is None or d.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="deployment not found")
    return d


async def create_deployment(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    payload: DeploymentCreate,
) -> Deployment:
    d = Deployment(
        tenant_id=tenant_id,
        agent_id=payload.agent_id,
        vicidial_server_id=payload.vicidial_server_id,
        vici_user=payload.vici_user,
        vici_pass_encrypted=encrypt(payload.vici_pass),
        phone_login=payload.phone_login,
        phone_pass_encrypted=encrypt(payload.phone_pass),
        campaign_id=payload.campaign_id,
        allowed_transfer_ingroups=list(payload.allowed_transfer_ingroups),
        dispo_mapping=payload.dispo_mapping,
        status="stopped",
    )
    session.add(d)
    await session.flush()
    await session.refresh(d)
    return d


async def update_deployment(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    deployment_id: UUID,
    payload: DeploymentUpdate,
) -> Deployment:
    d = await get_deployment(session, tenant_id=tenant_id, deployment_id=deployment_id)
    data = payload.model_dump(exclude_unset=True)
    if "vici_pass" in data and payload.vici_pass is not None:
        d.vici_pass_encrypted = encrypt(payload.vici_pass)
    if "phone_pass" in data and payload.phone_pass is not None:
        d.phone_pass_encrypted = encrypt(payload.phone_pass)
    for field in ("vici_user", "phone_login", "campaign_id",
                  "allowed_transfer_ingroups", "dispo_mapping"):
        if field in data and data[field] is not None:
            setattr(d, field, data[field])
    await session.flush()
    await session.refresh(d)
    return d


async def set_status(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    deployment_id: UUID,
    new_status: str,
) -> Deployment:
    d = await get_deployment(session, tenant_id=tenant_id, deployment_id=deployment_id)
    d.status = new_status
    await session.flush()
    return d


async def delete_deployment(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    deployment_id: UUID,
) -> None:
    d = await get_deployment(session, tenant_id=tenant_id, deployment_id=deployment_id)
    await session.delete(d)
    await session.flush()
