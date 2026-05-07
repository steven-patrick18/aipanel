"""Campaign CRUD + metrics + few-shot pool + manual mine trigger."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.deps import CurrentUser, TenantId
from ...auth.permissions import require_writer
from ...db.session import get_session
from ...jobs.arq_worker import get_arq
from ...schemas.campaign import (
    CampaignCreate,
    CampaignMetrics,
    CampaignRead,
    CampaignReadDetail,
    CampaignUpdate,
    FewShotExample,
)
from ...schemas.common import OkResponse, Page, PaginationParams
from ...services import campaigns_service
from ...services.audit_service import log_audit

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def _to_read(c) -> CampaignRead:
    pool = campaigns_service.parse_few_shot_pool(c.few_shot_pool)
    return CampaignRead(
        id=c.id, tenant_id=c.tenant_id, name=c.name, description=c.description,
        methodology=c.methodology, objective=c.objective,
        success_dispos=list(c.success_dispos or []),
        kb_collection_id=c.kb_collection_id, status=c.status,
        created_at=c.created_at, updated_at=c.updated_at,
        few_shot_updated_at=c.few_shot_updated_at,
        few_shot_count=len(pool),
    )


def _to_detail(c) -> CampaignReadDetail:
    pool = campaigns_service.parse_few_shot_pool(c.few_shot_pool)
    return CampaignReadDetail(
        **_to_read(c).model_dump(),
        persona_template=dict(c.persona_template or {}),
        script_template=dict(c.script_template or {}),
        few_shot_pool=pool,
    )


@router.get("", response_model=Page[CampaignRead])
async def list_campaigns(
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
) -> Page[CampaignRead]:
    items, total = await campaigns_service.list_campaigns(
        session, tenant_id=tenant_id,
        pagination=PaginationParams(limit=limit, offset=offset),
        status_filter=status_filter,
    )
    return Page(items=[_to_read(c) for c in items],
                total=total, limit=limit, offset=offset)


@router.get("/{campaign_id}", response_model=CampaignReadDetail)
async def get_campaign(
    campaign_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
) -> CampaignReadDetail:
    c = await campaigns_service.get_campaign(
        session, tenant_id=tenant_id, campaign_id=campaign_id,
    )
    return _to_detail(c)


@router.post("", response_model=CampaignReadDetail, status_code=201,
             dependencies=[Depends(require_writer)])
async def create_campaign(
    body: CampaignCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> CampaignReadDetail:
    c = await campaigns_service.create_campaign(
        session, tenant_id=user.tenant_id, payload=body,
    )
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="campaign.create", target_type="campaign",
                    target_id=c.id, payload={"name": c.name,
                                             "methodology": c.methodology})
    return _to_detail(c)


@router.patch("/{campaign_id}", response_model=CampaignReadDetail,
              dependencies=[Depends(require_writer)])
async def update_campaign(
    campaign_id: UUID,
    body: CampaignUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> CampaignReadDetail:
    c = await campaigns_service.update_campaign(
        session, tenant_id=user.tenant_id,
        campaign_id=campaign_id, payload=body,
    )
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="campaign.update", target_type="campaign",
                    target_id=c.id,
                    payload=body.model_dump(exclude_unset=True))
    return _to_detail(c)


@router.delete("/{campaign_id}", response_model=OkResponse,
               dependencies=[Depends(require_writer)])
async def archive_campaign(
    campaign_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> OkResponse:
    c = await campaigns_service.archive_campaign(
        session, tenant_id=user.tenant_id, campaign_id=campaign_id,
    )
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="campaign.archive", target_type="campaign",
                    target_id=c.id)
    return OkResponse()


@router.get("/{campaign_id}/metrics", response_model=CampaignMetrics)
async def metrics(
    campaign_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
    period_days: int = Query(30, ge=1, le=365),
) -> CampaignMetrics:
    return await campaigns_service.metrics(
        session, tenant_id=tenant_id, campaign_id=campaign_id,
        period_days=period_days,
    )


@router.get("/{campaign_id}/few-shot-pool",
            response_model=list[FewShotExample])
async def few_shot_pool(
    campaign_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
    limit: int = Query(20, ge=1, le=200),
) -> list[FewShotExample]:
    return await campaigns_service.get_few_shot_pool(
        session, tenant_id=tenant_id, campaign_id=campaign_id, limit=limit,
    )


@router.post("/{campaign_id}/refresh-few-shot", response_model=OkResponse,
             dependencies=[Depends(require_writer)])
async def refresh_few_shot(
    campaign_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
    arq: Annotated[ArqRedis, Depends(get_arq)],
) -> OkResponse:
    """Queue an out-of-band run of the few-shot mining job for this campaign."""
    await campaigns_service.get_campaign(
        session, tenant_id=user.tenant_id, campaign_id=campaign_id,
    )
    await arq.enqueue_job("campaign_mine_few_shot",
                          str(campaign_id), 30)   # 30-day window
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="campaign.refresh_few_shot",
                    target_type="campaign", target_id=campaign_id)
    return OkResponse()
