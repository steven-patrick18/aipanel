"""Analytics — straightforward SQL rollups over ``calls``.

For larger deployments these should move to materialized views refreshed
by the analytics_rollup ARQ job; v0.7 hits the live table directly.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models.agents import Agent
from ..db.models.calls import Call
from ..db.models.vici import Deployment
from ..schemas.analytics import (
    AgentRollup,
    AgentRollupResponse,
    OverviewResponse,
    TimeseriesPoint,
    TimeseriesResponse,
)


async def overview(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    period_start: date,
    period_end: date,
) -> OverviewResponse:
    p_start = datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc)
    p_end   = datetime.combine(period_end, datetime.max.time(), tzinfo=timezone.utc)

    base = (
        select(Call)
        .join(Deployment, Deployment.id == Call.deployment_id)
        .where(Deployment.tenant_id == tenant_id)
        .where(Call.started_at.between(p_start, p_end))
    )

    total = (await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()

    avg_dur = (await session.execute(
        select(func.coalesce(func.avg(Call.duration_sec), 0.0))
        .select_from(base.subquery())
    )).scalar_one()

    transfers = (await session.execute(
        select(func.count())
        .select_from(base.where(Call.transfer_target.is_not(None)).subquery())
    )).scalar_one()

    dispos = (await session.execute(
        select(Call.dispo_code, func.count())
        .select_from(base.subquery())
        .group_by(Call.dispo_code)
    )).all()
    breakdown = {d or "UNKNOWN": int(c) for d, c in dispos}

    return OverviewResponse(
        total_calls=int(total),
        avg_duration_sec=float(avg_dur or 0.0),
        transfer_rate=(transfers / total) if total else 0.0,
        dispo_breakdown=breakdown,
        period_start=period_start,
        period_end=period_end,
    )


async def per_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    period_start: date,
    period_end: date,
) -> AgentRollupResponse:
    p_start = datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc)
    p_end   = datetime.combine(period_end, datetime.max.time(), tzinfo=timezone.utc)

    transferred = case((Call.transfer_target.is_not(None), 1), else_=0)
    rows = (await session.execute(
        select(
            Agent.id, Agent.name,
            func.count(Call.id),
            func.coalesce(func.avg(Call.duration_sec), 0.0),
            func.coalesce(func.sum(transferred), 0),
        )
        .select_from(Agent)
        .join(Deployment, Deployment.agent_id == Agent.id)
        .join(Call, Call.deployment_id == Deployment.id)
        .where(Agent.tenant_id == tenant_id)
        .where(Call.started_at.between(p_start, p_end))
        .group_by(Agent.id, Agent.name)
    )).all()

    out: list[AgentRollup] = []
    for agent_id, name, total, avg_dur, transfers in rows:
        total_i = int(total or 0)
        out.append(AgentRollup(
            agent_id=agent_id,
            agent_name=name,
            total_calls=total_i,
            avg_duration_sec=float(avg_dur or 0.0),
            transfer_rate=(int(transfers or 0) / total_i) if total_i else 0.0,
            dispo_top=None,
        ))
    return AgentRollupResponse(rows=out)


async def timeseries(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    period_start: date,
    period_end: date,
    bucket: str = "day",
) -> TimeseriesResponse:
    p_start = datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc)
    p_end   = datetime.combine(period_end, datetime.max.time(), tzinfo=timezone.utc)
    if bucket not in ("hour", "day"):
        bucket = "day"
    trunc = func.date_trunc(bucket, Call.started_at)
    transferred = case((Call.transfer_target.is_not(None), 1), else_=0)

    rows = (await session.execute(
        select(
            trunc.label("bucket"),
            func.count(Call.id),
            func.coalesce(func.sum(transferred), 0),
            func.coalesce(func.avg(Call.duration_sec), 0.0),
        )
        .select_from(Call)
        .join(Deployment, Deployment.id == Call.deployment_id)
        .where(Deployment.tenant_id == tenant_id)
        .where(Call.started_at.between(p_start, p_end))
        .group_by("bucket")
        .order_by("bucket")
    )).all()

    points = [
        TimeseriesPoint(
            ts=ts,
            calls=int(calls or 0),
            transfers=int(transfers or 0),
            avg_duration_sec=float(avg_dur or 0.0),
        )
        for ts, calls, transfers, avg_dur in rows
    ]
    return TimeseriesResponse(bucket=bucket, points=points)
