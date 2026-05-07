"""Agent CRUD + custom actions."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
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
    TrainingRecordingRead,
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
# Training recordings — operator-uploaded audio. The transcription
# pipeline (faster-whisper → turn-pair extraction) feeds the resulting
# `{user, agent}` pairs into the agent's few-shot pool, so the LLM
# learns from real human conversations.
# ---------------------------------------------------------------------------


@router.get("/{agent_id}/training-recordings",
            response_model=list[TrainingRecordingRead])
async def list_training_recordings(
    agent_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
) -> list[TrainingRecordingRead]:
    a = await agents_service.get_agent(
        session, tenant_id=tenant_id, agent_id=agent_id,
    )
    return [TrainingRecordingRead.model_validate(x)
            for x in (a.training_recordings or [])]


@router.post("/{agent_id}/training-recordings",
             response_model=TrainingRecordingRead, status_code=201,
             dependencies=[Depends(require_writer)])
async def upload_training_recording(
    agent_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
    file: Annotated[UploadFile, File(...)],
    label: Annotated[str, Form()] = "",
) -> TrainingRecordingRead:
    """Accept a multipart audio upload, store it in MinIO, and queue
    the transcription job. Returns the recording in ``queued`` status;
    the worker updates it to ``ready`` once transcription finishes."""
    from datetime import datetime, timezone
    from uuid import uuid4

    a = await agents_service.get_agent(
        session, tenant_id=user.tenant_id, agent_id=agent_id,
    )

    contents = await file.read()
    if not contents:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="empty file",
        )

    cfg = get_config()
    rec_id = str(uuid4())
    storage_path = (
        f"s3://{cfg.minio.bucket_recordings}/training/"
        f"{user.tenant_id}/{agent_id}/{rec_id}-{file.filename}"
    )

    # Upload to MinIO synchronously via to_thread.
    import asyncio as _asyncio
    from io import BytesIO
    from minio import Minio

    def _put() -> None:
        client = Minio(
            cfg.minio.endpoint,
            access_key=cfg.minio.access_key,
            secret_key=cfg.minio.secret_key,
            secure=cfg.minio.secure,
        )
        # Bucket may not exist on first run.
        if not client.bucket_exists(cfg.minio.bucket_recordings):
            client.make_bucket(cfg.minio.bucket_recordings)
        key = storage_path[len(f"s3://{cfg.minio.bucket_recordings}/"):]
        client.put_object(
            cfg.minio.bucket_recordings, key,
            BytesIO(contents), len(contents),
            content_type=file.content_type or "application/octet-stream",
        )

    try:
        await _asyncio.to_thread(_put)
    except Exception as exc:                                 # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"object storage upload failed: {exc}",
        ) from exc

    entry = {
        "id": rec_id,
        "agent_id": str(agent_id),
        "filename": file.filename or "recording",
        "content_type": file.content_type or "application/octet-stream",
        "size_bytes": len(contents),
        "label": label,
        "storage_path": storage_path,
        "status": "queued",        # arq job picks this up
        "transcript": None,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "uploaded_by": str(user.id),
    }
    a.training_recordings = [*(a.training_recordings or []), entry]
    await session.flush()

    # Queue transcription job. Worker side picks up `agent_train_recording`.
    try:
        from ...jobs.arq_pool import get_arq_pool
        arq = await get_arq_pool()
        await arq.enqueue_job("agent_train_recording",
                              agent_id=str(agent_id),
                              recording_id=rec_id)
    except Exception:                                        # pragma: no cover
        # Queue unavailable in dev — the recording stays in `queued`
        # until the operator restarts the worker. Not fatal here.
        pass

    await log_audit(
        session, user_id=user.id, tenant_id=user.tenant_id,
        action="agent.training_recording_upload", target_type="agent",
        target_id=agent_id,
        payload={"filename": entry["filename"], "size": entry["size_bytes"]},
    )
    return TrainingRecordingRead.model_validate(entry)


@router.delete("/{agent_id}/training-recordings/{recording_id}",
               response_model=OkResponse,
               dependencies=[Depends(require_writer)])
async def delete_training_recording(
    agent_id: UUID,
    recording_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> OkResponse:
    a = await agents_service.get_agent(
        session, tenant_id=user.tenant_id, agent_id=agent_id,
    )
    before = len(a.training_recordings or [])
    a.training_recordings = [
        x for x in (a.training_recordings or []) if x.get("id") != recording_id
    ]
    if len(a.training_recordings) == before:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="training recording not found",
        )
    await session.flush()
    await log_audit(
        session, user_id=user.id, tenant_id=user.tenant_id,
        action="agent.training_recording_delete", target_type="agent",
        target_id=agent_id, payload={"recording_id": recording_id},
    )
    return OkResponse()
