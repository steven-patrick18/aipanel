"""Cluster endpoints — single-node v1, multi-node feature-flagged off."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.deps import CurrentUser
from ...auth.permissions import require_admin
from ...db.models.ops import Node
from ...db.session import get_session
from ...schemas.system import JoinTokenResponse, NodeRead

router = APIRouter(prefix="/cluster", tags=["cluster"])


@router.get("/nodes", response_model=list[NodeRead])
async def list_nodes(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: CurrentUser,
) -> list[NodeRead]:
    rows = (await session.execute(
        select(Node).order_by(Node.role.asc(), Node.hostname.asc())
    )).scalars().all()
    return [
        NodeRead(
            id=n.id, hostname=n.hostname, role=n.role,
            services=list(n.services or []),
            status=n.status,
            last_heartbeat_at=n.last_heartbeat_at,
            joined_at=n.joined_at,
        )
        for n in rows
    ]


@router.get("/health")
async def cluster_health(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: CurrentUser,
) -> dict:
    rows = (await session.execute(
        select(Node).where(Node.status != "down")
    )).scalars().all()
    return {"healthy_nodes": len(rows)}


@router.post("/join-token", response_model=JoinTokenResponse,
             dependencies=[Depends(require_admin)])
async def join_token() -> JoinTokenResponse:
    return JoinTokenResponse()
