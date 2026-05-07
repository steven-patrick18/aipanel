"""Knowledge-base CRUD + search.

Search is a stub for v0.7 — the ``aipanel-jobs`` worker will run the
real ingest + embed pipeline once pgvector + an embed-server land. For
now ``search`` returns an empty hit list.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models.agents import KbDocument, KnowledgeBase
from ..schemas.common import PaginationParams
from ..schemas.kb import KbCreate, KbSearchHit, KbSearchResponse


async def list_kbs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    pagination: PaginationParams,
) -> tuple[list[KnowledgeBase], int]:
    base = select(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant_id)
    total = (await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()
    rows = (await session.execute(
        base.order_by(KnowledgeBase.created_at.desc())
            .limit(pagination.limit).offset(pagination.offset)
    )).scalars().all()
    return list(rows), int(total)


async def get_kb(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    kb_id: UUID,
) -> KnowledgeBase:
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None or kb.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="kb not found")
    return kb


async def create_kb(
    session: AsyncSession, *, tenant_id: UUID, payload: KbCreate,
) -> KnowledgeBase:
    kb = KnowledgeBase(
        tenant_id=tenant_id,
        name=payload.name,
        description=payload.description,
        embedding_model=payload.embedding_model,
    )
    session.add(kb)
    await session.flush()
    await session.refresh(kb)
    return kb


async def list_documents(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    kb_id: UUID,
) -> list[KbDocument]:
    await get_kb(session, tenant_id=tenant_id, kb_id=kb_id)
    rows = (await session.execute(
        select(KbDocument).where(KbDocument.kb_id == kb_id)
                          .order_by(KbDocument.created_at.desc())
    )).scalars().all()
    return list(rows)


async def create_document_pending(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    kb_id: UUID,
    filename: str,
    content_hash: str,
) -> KbDocument:
    await get_kb(session, tenant_id=tenant_id, kb_id=kb_id)
    doc = KbDocument(
        kb_id=kb_id,
        filename=filename,
        content_hash=content_hash,
        chunk_count=0,
        status="pending",
    )
    session.add(doc)
    await session.flush()
    await session.refresh(doc)
    return doc


async def delete_document(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    kb_id: UUID,
    doc_id: UUID,
) -> None:
    await get_kb(session, tenant_id=tenant_id, kb_id=kb_id)
    doc = await session.get(KbDocument, doc_id)
    if doc is None or doc.kb_id != kb_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="document not found")
    await session.delete(doc)
    await session.flush()


async def search(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    kb_id: UUID,
    query: str,
    limit: int,
) -> KbSearchResponse:
    """Real search via embed-server + pgvector cosine similarity."""
    from sqlalchemy import text as sql_text

    from ..config import get_config
    from ..integrations.embed_client import EmbedClient

    await get_kb(session, tenant_id=tenant_id, kb_id=kb_id)

    cfg = get_config()
    embed_url = (
        getattr(getattr(cfg, "embed", None), "endpoint", None)
        or "http://127.0.0.1:8004"
    )
    embed = EmbedClient(embed_url)
    try:
        vec = await embed.embed(query)
    finally:
        await embed.aclose()
    if vec is None:
        return KbSearchResponse(hits=[])

    vec_lit = "[" + ",".join(f"{x:.7f}" for x in vec) + "]"

    # 1 - cosine_distance gives a 0..1 similarity score; bigger = better.
    rows = (await session.execute(
        sql_text(
            "SELECT id, document_id, chunk_text, "
            "       1 - (embedding <=> CAST(:vec AS vector)) AS score "
            "  FROM kb_chunks "
            " WHERE kb_id = :kb_id "
            " ORDER BY embedding <=> CAST(:vec AS vector) "
            " LIMIT :lim"
        ),
        {"vec": vec_lit, "kb_id": str(kb_id), "lim": limit},
    )).all()

    hits = [
        KbSearchHit(
            chunk_text=row.chunk_text,
            score=float(row.score),
            document_id=row.document_id,
        )
        for row in rows
    ]
    return KbSearchResponse(hits=hits)
