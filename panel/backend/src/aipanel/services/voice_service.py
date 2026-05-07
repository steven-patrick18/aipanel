"""Voice CRUD + clone bridge to the TTS server."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models.agents import Voice
from ..schemas.common import PaginationParams


async def list_voices(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    pagination: PaginationParams,
) -> tuple[list[Voice], int]:
    base = select(Voice).where(Voice.tenant_id == tenant_id)
    total = (await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()
    rows = (await session.execute(
        base.order_by(Voice.created_at.desc())
            .limit(pagination.limit)
            .offset(pagination.offset)
    )).scalars().all()
    return list(rows), int(total)


async def get_voice(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    voice_id: UUID,
) -> Voice:
    v = await session.get(Voice, voice_id)
    if v is None or v.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="voice not found")
    return v


async def create_voice_pending(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    name: str,
) -> Voice:
    """Inserts a placeholder row in ``status=pending``. The ARQ worker fills
    in ``sample_path`` / ``embedding_path`` and flips status to ``ready``."""
    v = Voice(tenant_id=tenant_id, name=name, status="pending")
    session.add(v)
    await session.flush()
    await session.refresh(v)
    return v


async def mark_voice_ready(
    session: AsyncSession,
    *,
    voice_id: UUID,
    sample_path: str,
    embedding_path: str,
) -> None:
    v = await session.get(Voice, voice_id)
    if v is None:
        return
    v.sample_path = sample_path
    v.embedding_path = embedding_path
    v.status = "ready"
    await session.flush()


async def mark_voice_error(
    session: AsyncSession,
    *,
    voice_id: UUID,
) -> None:
    v = await session.get(Voice, voice_id)
    if v is None:
        return
    v.status = "error"
    await session.flush()


async def delete_voice(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    voice_id: UUID,
) -> None:
    v = await get_voice(session, tenant_id=tenant_id, voice_id=voice_id)
    await session.delete(v)
    await session.flush()
