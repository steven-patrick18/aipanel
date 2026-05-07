"""Voice CRUD + clone (multipart) + preview."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.deps import CurrentUser, TenantId
from ...auth.permissions import require_writer
from ...config import get_config
from ...db.session import get_session
from ...integrations.tts_client import TTSClient
from ...jobs.arq_worker import get_arq
from ...schemas.common import OkResponse, Page, PaginationParams
from ...schemas.voice import VoiceCreateForm, VoicePreviewRequest, VoiceRead
from ...services import voice_service
from ...services.audit_service import log_audit

router = APIRouter(prefix="/voices", tags=["voices"])


@router.get("", response_model=Page[VoiceRead])
async def list_voices(
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
    limit: int = 50,
    offset: int = 0,
) -> Page[VoiceRead]:
    items, total = await voice_service.list_voices(
        session, tenant_id=tenant_id,
        pagination=PaginationParams(limit=limit, offset=offset),
    )
    return Page(items=[VoiceRead.model_validate(v) for v in items],
                total=total, limit=limit, offset=offset)


@router.post("", response_model=VoiceRead, status_code=202,
             dependencies=[Depends(require_writer)])
async def create_voice(
    name: Annotated[str, Form(...)],
    ref_text: Annotated[str, Form(...)],
    audio: Annotated[UploadFile, File(...)],
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
    arq: Annotated[ArqRedis, Depends(get_arq)],
) -> VoiceRead:
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="empty audio upload")
    v = await voice_service.create_voice_pending(
        session, tenant_id=user.tenant_id, name=name,
    )
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="voice.create", target_type="voice", target_id=v.id,
                    payload={"name": name, "filename": audio.filename})
    # Hand the raw bytes to the ARQ worker — base64 in the job payload.
    import base64
    await arq.enqueue_job(
        "voice_clone",
        str(v.id), str(user.tenant_id), name, ref_text,
        base64.b64encode(audio_bytes).decode("ascii"),
        audio.filename or "ref.wav",
    )
    return VoiceRead.model_validate(v)


@router.get("/{voice_id}", response_model=VoiceRead)
async def get_voice(
    voice_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
) -> VoiceRead:
    v = await voice_service.get_voice(session, tenant_id=tenant_id, voice_id=voice_id)
    return VoiceRead.model_validate(v)


@router.delete("/{voice_id}", response_model=OkResponse,
               dependencies=[Depends(require_writer)])
async def delete_voice(
    voice_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> OkResponse:
    await voice_service.delete_voice(
        session, tenant_id=user.tenant_id, voice_id=voice_id,
    )
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="voice.delete", target_type="voice", target_id=voice_id)
    return OkResponse()


@router.post("/{voice_id}/preview")
async def preview_voice(
    voice_id: UUID,
    body: VoicePreviewRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
):
    v = await voice_service.get_voice(session, tenant_id=tenant_id, voice_id=voice_id)
    if v.status != "ready":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"voice status is {v.status!r}, expected 'ready'")
    cfg = get_config()

    async def _stream():
        async with TTSClient(cfg.tts.endpoint) as tts:
            async for chunk in tts.synthesize_stream(
                text=body.text, voice_id=str(v.id),
                output_format="pcm_s16le_24000",
            ):
                yield chunk

    return StreamingResponse(_stream(), media_type="audio/L16")
