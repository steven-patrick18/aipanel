"""Knowledge bases — CRUD, document upload (queues ingest), search."""

from __future__ import annotations

import hashlib
from typing import Annotated
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.deps import CurrentUser, TenantId
from ...auth.permissions import require_writer
from ...db.session import get_session
from ...jobs.arq_worker import get_arq
from ...schemas.common import OkResponse, Page, PaginationParams
from ...schemas.kb import (
    KbCreate,
    KbDocumentRead,
    KbRead,
    KbSearchRequest,
    KbSearchResponse,
)
from ...services import kb_service
from ...services.audit_service import log_audit

router = APIRouter(prefix="/kb", tags=["kb"])


@router.get("", response_model=Page[KbRead])
async def list_kbs(
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
    limit: int = 50, offset: int = 0,
) -> Page[KbRead]:
    items, total = await kb_service.list_kbs(
        session, tenant_id=tenant_id,
        pagination=PaginationParams(limit=limit, offset=offset),
    )
    return Page(items=[KbRead.model_validate(k) for k in items],
                total=total, limit=limit, offset=offset)


@router.post("", response_model=KbRead, status_code=201,
             dependencies=[Depends(require_writer)])
async def create_kb(
    body: KbCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> KbRead:
    kb = await kb_service.create_kb(session, tenant_id=user.tenant_id, payload=body)
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="kb.create", target_type="kb", target_id=kb.id,
                    payload={"name": body.name})
    return KbRead.model_validate(kb)


@router.get("/{kb_id}/documents", response_model=list[KbDocumentRead])
async def list_documents(
    kb_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
) -> list[KbDocumentRead]:
    docs = await kb_service.list_documents(session, tenant_id=tenant_id, kb_id=kb_id)
    return [KbDocumentRead.model_validate(d) for d in docs]


@router.post("/{kb_id}/documents", response_model=KbDocumentRead, status_code=202,
             dependencies=[Depends(require_writer)])
async def upload_document(
    kb_id: UUID,
    file: Annotated[UploadFile, File(...)],
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
    arq: Annotated[ArqRedis, Depends(get_arq)],
) -> KbDocumentRead:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="empty upload")
    h = hashlib.sha256(raw).hexdigest()
    doc = await kb_service.create_document_pending(
        session, tenant_id=user.tenant_id, kb_id=kb_id,
        filename=file.filename or "upload.bin", content_hash=h,
    )
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="kb.upload_document", target_type="kb_document",
                    target_id=doc.id,
                    payload={"kb_id": str(kb_id), "filename": doc.filename,
                             "bytes": len(raw)})
    import base64
    await arq.enqueue_job(
        "kb_ingest_document",
        str(doc.id), str(kb_id), doc.filename,
        base64.b64encode(raw).decode("ascii"),
    )
    return KbDocumentRead.model_validate(doc)


@router.delete("/{kb_id}/documents/{doc_id}", response_model=OkResponse,
               dependencies=[Depends(require_writer)])
async def delete_document(
    kb_id: UUID, doc_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> OkResponse:
    await kb_service.delete_document(
        session, tenant_id=user.tenant_id, kb_id=kb_id, doc_id=doc_id,
    )
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="kb.delete_document", target_type="kb_document",
                    target_id=doc_id)
    return OkResponse()


@router.post("/{kb_id}/search", response_model=KbSearchResponse)
async def search_kb(
    kb_id: UUID,
    body: KbSearchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
) -> KbSearchResponse:
    return await kb_service.search(
        session, tenant_id=tenant_id, kb_id=kb_id,
        query=body.query, limit=body.limit,
    )
