"""Campaign CRUD + metrics + few-shot pool helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models.calls import Call
from ..db.models.campaigns import Campaign
from ..db.models.vici import Deployment
from ..schemas.campaign import (
    CampaignCreate,
    CampaignMetrics,
    CampaignUpdate,
    FewShotExample,
)
from ..schemas.common import PaginationParams


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def list_campaigns(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    pagination: PaginationParams,
    status_filter: str | None = None,
) -> tuple[list[Campaign], int]:
    base = select(Campaign).where(Campaign.tenant_id == tenant_id)
    if status_filter:
        base = base.where(Campaign.status == status_filter)
    total = (await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()
    rows = (await session.execute(
        base.order_by(Campaign.updated_at.desc())
            .limit(pagination.limit)
            .offset(pagination.offset)
    )).scalars().all()
    return list(rows), int(total)


async def get_campaign(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID,
) -> Campaign:
    c = await session.get(Campaign, campaign_id)
    if c is None or c.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="campaign not found")
    return c


async def create_campaign(
    session: AsyncSession, *, tenant_id: UUID, payload: CampaignCreate,
) -> Campaign:
    c = Campaign(
        tenant_id=tenant_id,
        name=payload.name,
        description=payload.description,
        methodology=payload.methodology,
        objective=payload.objective,
        success_dispos=list(payload.success_dispos),
        persona_template=dict(payload.persona_template),
        script_template=dict(payload.script_template),
        kb_collection_id=payload.kb_collection_id,
        few_shot_pool=[],
        status="draft",
    )
    session.add(c)
    await session.flush()
    await session.refresh(c)
    return c


async def update_campaign(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    payload: CampaignUpdate,
) -> Campaign:
    c = await get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    data = payload.model_dump(exclude_unset=True)
    for field in ("name", "description", "methodology", "objective",
                  "success_dispos", "persona_template", "script_template",
                  "kb_collection_id", "status"):
        if field in data and data[field] is not None:
            setattr(c, field, data[field])
    await session.flush()
    await session.refresh(c)
    return c


async def archive_campaign(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID,
) -> Campaign:
    c = await get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    c.status = "archived"
    await session.flush()
    return c


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

async def metrics(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    period_days: int = 30,
) -> CampaignMetrics:
    c = await get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    since = datetime.now(timezone.utc) - timedelta(days=period_days)

    # All calls for this campaign in window. We match either calls.campaign_id
    # directly or via deployments.aipanel_campaign_id (covers older rows that
    # didn't get the denormalised campaign_id stamped on the call row).
    base = (
        select(Call)
        .join(Deployment, Deployment.id == Call.deployment_id)
        .where(Deployment.tenant_id == tenant_id)
        .where(Call.started_at >= since)
        .where(
            (Call.campaign_id == campaign_id)
            | (Deployment.aipanel_campaign_id == campaign_id)
        )
    )

    total = (await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()

    # Successful = dispo in campaign.success_dispos.
    successful = 0
    by_dispo: dict[str, int] = {}
    if total:
        rows = (await session.execute(
            select(Call.dispo_code, func.count()).select_from(base.subquery())
                                                 .group_by(Call.dispo_code)
        )).all()
        for d, n in rows:
            key = d or "UNKNOWN"
            by_dispo[key] = int(n)
            if d in (c.success_dispos or []):
                successful += int(n)

    avg_dur = (await session.execute(
        select(func.coalesce(func.avg(Call.duration_sec), 0.0))
        .select_from(base.subquery())
    )).scalar_one()

    return CampaignMetrics(
        campaign_id=campaign_id,
        period_days=period_days,
        total_calls=int(total),
        successful_calls=int(successful),
        conversion_rate=(successful / total) if total else 0.0,
        by_dispo=by_dispo,
        avg_duration_sec=float(avg_dur or 0.0),
    )


# ---------------------------------------------------------------------------
# Few-shot pool reads
# ---------------------------------------------------------------------------

def parse_few_shot_pool(raw: Any) -> list[FewShotExample]:
    if not raw:
        return []
    out: list[FewShotExample] = []
    for item in raw:
        try:
            out.append(FewShotExample(**item))
        except Exception:
            continue
    return out


async def get_few_shot_pool(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    limit: int = 20,
) -> list[FewShotExample]:
    c = await get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    pool = parse_few_shot_pool(c.few_shot_pool)
    pool.sort(key=lambda e: e.score, reverse=True)
    return pool[:limit]
