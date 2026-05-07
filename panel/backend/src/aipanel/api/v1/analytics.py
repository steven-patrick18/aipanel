"""Analytics endpoints — overview, per-agent rollup, timeseries."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.deps import TenantId
from ...db.session import get_session
from ...schemas.analytics import (
    AgentRollupResponse,
    OverviewResponse,
    TimeseriesResponse,
)
from ...services import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _default_period(days_back: int = 7) -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=days_back), today


@router.get("/overview", response_model=OverviewResponse)
async def overview(
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
    period_start: date | None = Query(None),
    period_end: date | None = Query(None),
) -> OverviewResponse:
    if period_start is None or period_end is None:
        period_start, period_end = _default_period()
    return await analytics_service.overview(
        session, tenant_id=tenant_id,
        period_start=period_start, period_end=period_end,
    )


@router.get("/agents", response_model=AgentRollupResponse)
async def per_agent(
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
    period_start: date | None = Query(None),
    period_end: date | None = Query(None),
) -> AgentRollupResponse:
    if period_start is None or period_end is None:
        period_start, period_end = _default_period(30)
    return await analytics_service.per_agent(
        session, tenant_id=tenant_id,
        period_start=period_start, period_end=period_end,
    )


@router.get("/timeseries", response_model=TimeseriesResponse)
async def timeseries(
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
    bucket: Literal["hour", "day"] = "day",
    period_start: date | None = Query(None),
    period_end: date | None = Query(None),
) -> TimeseriesResponse:
    if period_start is None or period_end is None:
        period_start, period_end = _default_period(30)
    return await analytics_service.timeseries(
        session, tenant_id=tenant_id, bucket=bucket,
        period_start=period_start, period_end=period_end,
    )
