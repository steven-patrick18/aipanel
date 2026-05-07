"""Call list, detail, transcript, recording presigned URL."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.deps import CurrentUser, TenantId
from ...auth.permissions import require_writer
from ...config import get_config
from ...db.models.calls import Call, CallEvent
from ...db.models.vici import Deployment
from ...db.session import get_session
from ...integrations.session_mgr_client import SessionMgrClient
from ...schemas.call import (
    CallEventRead,
    CallSummary,
    CallTranscript,
    RecordingUrl,
    TranscriptTurn,
)
from ...schemas.common import OkResponse, Page
from ...services.audit_service import log_audit

router = APIRouter(prefix="/calls", tags=["calls"])


async def _get_call_for_tenant(
    session: AsyncSession, tenant_id: UUID, call_id: UUID,
) -> Call:
    row = (await session.execute(
        select(Call)
        .join(Deployment, Deployment.id == Call.deployment_id)
        .where(Call.id == call_id)
        .where(Deployment.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="call not found")
    return row


@router.get("", response_model=Page[CallSummary])
async def list_calls(
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    deployment_id: UUID | None = None,
    outcome: str | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
) -> Page[CallSummary]:
    base = (
        select(Call)
        .join(Deployment, Deployment.id == Call.deployment_id)
        .where(Deployment.tenant_id == tenant_id)
    )
    if deployment_id:
        base = base.where(Call.deployment_id == deployment_id)
    if outcome:
        base = base.where(Call.outcome == outcome)
    if started_after:
        base = base.where(Call.started_at >= started_after)
    if started_before:
        base = base.where(Call.started_at <= started_before)

    total = (await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()
    rows = (await session.execute(
        base.order_by(Call.started_at.desc())
            .limit(limit).offset(offset)
    )).scalars().all()
    return Page(items=[CallSummary.model_validate(r) for r in rows],
                total=int(total), limit=limit, offset=offset)


@router.get("/{call_id}", response_model=CallSummary)
async def get_call(
    call_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
) -> CallSummary:
    call = await _get_call_for_tenant(session, tenant_id, call_id)
    return CallSummary.model_validate(call)


@router.get("/{call_id}/events", response_model=list[CallEventRead])
async def get_events(
    call_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
) -> list[CallEventRead]:
    await _get_call_for_tenant(session, tenant_id, call_id)
    rows = (await session.execute(
        select(CallEvent).where(CallEvent.call_id == call_id)
                         .order_by(CallEvent.ts.asc())
    )).scalars().all()
    return [CallEventRead.model_validate(r) for r in rows]


@router.get("/{call_id}/transcript", response_model=CallTranscript)
async def get_transcript(
    call_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
) -> CallTranscript:
    await _get_call_for_tenant(session, tenant_id, call_id)
    rows = (await session.execute(
        select(CallEvent).where(CallEvent.call_id == call_id)
                         .where(CallEvent.event_type.in_(
                             ["user_speech", "agent_speech"]
                         ))
                         .order_by(CallEvent.ts.asc())
    )).scalars().all()
    turns = [
        TranscriptTurn(
            ts=r.ts,
            role="user" if r.event_type == "user_speech" else "agent",
            text=str(r.payload.get("text", "")),
            extra={k: v for k, v in r.payload.items() if k != "text"},
        )
        for r in rows
    ]
    return CallTranscript(call_id=call_id, turns=turns)


@router.get("/{call_id}/recording", response_model=RecordingUrl)
async def get_recording(
    call_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
) -> RecordingUrl:
    call = await _get_call_for_tenant(session, tenant_id, call_id)
    if not call.recording_path:
        raise HTTPException(status_code=404, detail="no recording for this call")
    cfg = get_config()
    # Parse s3://bucket/key from recording_path.
    p = call.recording_path
    if not p.startswith("s3://"):
        raise HTTPException(status_code=500,
                            detail=f"unexpected recording_path format: {p!r}")
    rest = p[len("s3://"):]
    bucket, _, key = rest.partition("/")
    if not key:
        raise HTTPException(status_code=500,
                            detail="recording_path missing object key")
    # Build a presigned URL synchronously (minio SDK is sync).
    import asyncio as _asyncio
    from datetime import timedelta
    from minio import Minio

    def _sign() -> str:
        client = Minio(
            cfg.minio.endpoint,
            access_key=cfg.minio.access_key,
            secret_key=cfg.minio.secret_key,
            secure=cfg.minio.secure,
        )
        return client.presigned_get_object(
            bucket, key, expires=timedelta(seconds=3600),
        )

    url = await _asyncio.to_thread(_sign)
    return RecordingUrl(url=url, expires_in=3600)


# ---------------------------------------------------------------------------
# Live-call actions — operator overrides on an in-progress call
# ---------------------------------------------------------------------------


class CallTransferRequest(BaseModel):
    ingroup_id: str = Field(..., min_length=1, max_length=64)
    summary: str = Field("", max_length=2000)


class IngroupOption(BaseModel):
    id: str
    label: str


@router.get("/{call_id}/transfer-options", response_model=list[IngroupOption])
async def list_transfer_options(
    call_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
) -> list[IngroupOption]:
    """Allowed ingroups the operator can transfer this live call into.

    The list comes from the deployment's ``allowed_transfer_ingroups``
    column — locking down which queues a human is allowed to send a
    call to keeps customer-facing routing predictable.
    """
    call = await _get_call_for_tenant(session, tenant_id, call_id)
    deployment = await session.get(Deployment, call.deployment_id)
    if deployment is None:
        return []
    return [
        IngroupOption(id=str(ig), label=str(ig))
        for ig in (deployment.allowed_transfer_ingroups or [])
    ]


@router.post("/{call_id}/transfer", response_model=OkResponse,
             dependencies=[Depends(require_writer)])
async def transfer_call(
    call_id: UUID,
    body: CallTransferRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> OkResponse:
    """Operator-initiated warm transfer of a live AI call into a ViciDial ingroup.

    The dialler bridges the customer leg into the chosen ingroup
    conference; the AI agent leg is dropped after the handoff. The
    requested ingroup must already be on the deployment's allow-list
    (set per-deployment so each campaign controls where its calls can
    end up routed).
    """
    call = await _get_call_for_tenant(session, user.tenant_id, call_id)

    if call.ended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this call has already ended — cannot transfer",
        )

    deployment = await session.get(Deployment, call.deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="deployment for this call no longer exists",
        )

    allowed = set(deployment.allowed_transfer_ingroups or [])
    if allowed and body.ingroup_id not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"ingroup '{body.ingroup_id}' is not in this deployment's "
                f"allow-list ({sorted(allowed)})"
            ),
        )

    cfg = get_config()
    import os
    token = os.environ.get("SESSION_MGR_TOKEN", "")
    base = cfg.vici.url or "http://127.0.0.1:8010"
    async with SessionMgrClient(base, token, timeout_sec=10.0) as sm:
        ok, detail = await sm.transfer(
            str(deployment.id), body.ingroup_id, body.summary,
        )
    if not ok:
        await log_audit(
            session, user_id=user.id, tenant_id=user.tenant_id,
            action="call.transfer_failed", target_type="call",
            target_id=call_id,
            payload={"ingroup_id": body.ingroup_id, "error": detail},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"session manager rejected transfer: {detail}",
        )

    call.transfer_target = body.ingroup_id
    await session.flush()
    await log_audit(
        session, user_id=user.id, tenant_id=user.tenant_id,
        action="call.transfer", target_type="call", target_id=call_id,
        payload={"ingroup_id": body.ingroup_id, "summary": body.summary},
    )
    return OkResponse()


# ---------------------------------------------------------------------------
# Mark a call (or one turn from a call) as an exemplar — pushes a
# `kind=call` training example onto the agent's training_examples list.
# ---------------------------------------------------------------------------


@router.post("/{call_id}/mark-exemplar", response_model=OkResponse,
             dependencies=[Depends(require_writer)])
async def mark_exemplar(
    call_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
    body: dict | None = None,
) -> OkResponse:
    """Pin one user→agent turn pair from this call as a training example.

    Body:
      ``{"agent_id": uuid?, "user_turn": str, "agent_turn": str, "notes": str?}``

    If ``agent_id`` is omitted the call's deployment.agent_id is used,
    so the operator only needs to type the two transcript lines they
    want the model to imitate.
    """
    from datetime import datetime, timezone
    from uuid import UUID as _UUID, uuid4
    from ...db.models.agents import Agent

    body = body or {}
    user_turn = (body.get("user_turn") or "").strip()
    agent_turn = (body.get("agent_turn") or "").strip()
    if not user_turn or not agent_turn:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="user_turn and agent_turn are required",
        )

    call = await _get_call_for_tenant(session, user.tenant_id, call_id)

    # Resolve target agent.
    if body.get("agent_id"):
        try:
            agent_id = _UUID(str(body["agent_id"]))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="agent_id must be a UUID",
            ) from exc
    else:
        deployment = await session.get(Deployment, call.deployment_id)
        if deployment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="deployment for this call no longer exists",
            )
        agent_id = deployment.agent_id

    agent = await session.get(Agent, agent_id)
    if agent is None or agent.tenant_id != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="agent not found",
        )

    entry = {
        "id": str(uuid4()),
        "kind": "call",
        "call_id": str(call_id),
        "user": user_turn,
        "agent": agent_turn,
        "notes": (body.get("notes") or "").strip(),
        "recording_path": call.recording_path,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "added_by": str(user.id),
    }
    agent.training_examples = [*(agent.training_examples or []), entry]
    await session.flush()
    await log_audit(
        session, user_id=user.id, tenant_id=user.tenant_id,
        action="call.mark_exemplar", target_type="call", target_id=call_id,
        payload={"agent_id": str(agent_id)},
    )
    return OkResponse()
