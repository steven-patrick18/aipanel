"""ViciDial server registration."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.deps import CurrentUser, TenantId
from ...auth.permissions import require_writer
from ...crypto import encrypt
from ...db.models.vici import VicidialServer
from ...db.session import get_session
from ...schemas.common import OkResponse, Page, PaginationParams
from ...schemas.vicidial import (
    VicidialServerCreate,
    VicidialServerRead,
    VicidialServerUpdate,
    VicidialTestResult,
)
from ...services.audit_service import log_audit

router = APIRouter(prefix="/vicidial-servers", tags=["vicidial"])


@router.get("", response_model=Page[VicidialServerRead])
async def list_servers(
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
    limit: int = 50, offset: int = 0,
) -> Page[VicidialServerRead]:
    base = select(VicidialServer).where(VicidialServer.tenant_id == tenant_id)
    total = (await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()
    rows = (await session.execute(
        base.order_by(VicidialServer.created_at.desc())
            .limit(limit).offset(offset)
    )).scalars().all()
    return Page(
        items=[VicidialServerRead.model_validate(r) for r in rows],
        total=int(total), limit=limit, offset=offset,
    )


@router.post("", response_model=VicidialServerRead, status_code=201,
             dependencies=[Depends(require_writer)])
async def create_server(
    body: VicidialServerCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> VicidialServerRead:
    s = VicidialServer(
        tenant_id=user.tenant_id,
        name=body.name,
        asterisk_host=body.asterisk_host,
        asterisk_port=body.asterisk_port,
        web_url=str(body.web_url),
        ami_user=body.ami_user,
        ami_pass_encrypted=encrypt(body.ami_pass),
        web_user_admin=body.web_user_admin,
        web_pass_encrypted=encrypt(body.web_pass),
    )
    session.add(s)
    await session.flush()
    await session.refresh(s)
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="vicidial_server.create",
                    target_type="vicidial_server", target_id=s.id,
                    payload={"name": body.name, "host": body.asterisk_host})
    return VicidialServerRead.model_validate(s)


@router.patch("/{server_id}", response_model=VicidialServerRead,
              dependencies=[Depends(require_writer)])
async def update_server(
    server_id: UUID,
    body: VicidialServerUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> VicidialServerRead:
    s = await session.get(VicidialServer, server_id)
    if s is None or s.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="server not found")
    data = body.model_dump(exclude_unset=True)
    if "ami_pass" in data and body.ami_pass is not None:
        s.ami_pass_encrypted = encrypt(body.ami_pass)
    if "web_pass" in data and body.web_pass is not None:
        s.web_pass_encrypted = encrypt(body.web_pass)
    if "web_url" in data and body.web_url is not None:
        s.web_url = str(body.web_url)
    for field in ("name", "asterisk_host", "asterisk_port",
                  "ami_user", "web_user_admin"):
        if field in data and data[field] is not None:
            setattr(s, field, data[field])
    await session.flush()
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="vicidial_server.update",
                    target_type="vicidial_server", target_id=s.id,
                    payload=body.model_dump(exclude_unset=True,
                                             exclude={"ami_pass", "web_pass"}))
    return VicidialServerRead.model_validate(s)


@router.post("/{server_id}/test-connection", response_model=VicidialTestResult)
async def test_connection(
    server_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_id: TenantId,
) -> VicidialTestResult:
    s = await session.get(VicidialServer, server_id)
    if s is None or s.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="server not found")
    # Real test would use the session-mgr's adapter to attempt a login.
    # For v0.7 we return a placeholder so the UI can wire the button up.
    return VicidialTestResult(
        web_login_ok=False,
        web_error="test-connection requires aipanel-session-mgr to expose a probe endpoint",
        ami_ok=False,
        ami_error="not implemented in v0.7",
    )
