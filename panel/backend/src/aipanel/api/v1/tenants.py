"""Tenant CRUD + user invite. Admin-only."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.deps import CurrentUser
from ...auth.jwt import hash_password
from ...auth.permissions import require_admin
from ...db.models.tenants import Tenant, User
from ...db.session import get_session
from ...schemas.auth import UserPublic
from ...schemas.common import OkResponse
from ...schemas.tenant import TenantCreate, TenantRead, TenantUpdate, UserInvite
from ...services.audit_service import log_audit

router = APIRouter(prefix="/tenants", tags=["tenants"],
                   dependencies=[Depends(require_admin)])


@router.get("", response_model=list[TenantRead])
async def list_tenants(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> list[TenantRead]:
    # Admins see only their own tenant — true superadmin / cross-tenant
    # listing belongs to a future "owner" role.
    rows = (await session.execute(
        select(Tenant).where(Tenant.id == user.tenant_id)
    )).scalars().all()
    return [TenantRead.model_validate(t) for t in rows]


@router.post("", response_model=TenantRead, status_code=201)
async def create_tenant(
    body: TenantCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> TenantRead:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="cross-tenant creation requires the not-yet-implemented 'owner' role",
    )


@router.patch("/{tenant_id}", response_model=TenantRead)
async def update_tenant(
    tenant_id: UUID,
    body: TenantUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> TenantRead:
    if tenant_id != user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="tenant not found")
    t = await session.get(Tenant, tenant_id)
    if t is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="tenant not found")
    if body.name is not None:
        t.name = body.name
    if body.settings is not None:
        t.settings = body.settings
    await session.flush()
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="tenant.update", target_type="tenant",
                    target_id=tenant_id,
                    payload=body.model_dump(exclude_unset=True))
    return TenantRead.model_validate(t)


@router.get("/{tenant_id}/users", response_model=list[UserPublic])
async def list_users(
    tenant_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> list[UserPublic]:
    if tenant_id != user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="tenant not found")
    rows = (await session.execute(
        select(User).where(User.tenant_id == tenant_id).order_by(User.created_at.asc())
    )).scalars().all()
    return [UserPublic.model_validate(u) for u in rows]


@router.post("/{tenant_id}/users", response_model=UserPublic, status_code=201)
async def invite_user(
    tenant_id: UUID,
    body: UserInvite,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> UserPublic:
    if tenant_id != user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="tenant not found")
    new_user = User(
        tenant_id=tenant_id,
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        role=body.role,
    )
    session.add(new_user)
    try:
        await session.flush()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="email already in use") from exc
    await log_audit(session, user_id=user.id, tenant_id=tenant_id,
                    action="user.invite", target_type="user",
                    target_id=new_user.id,
                    payload={"email": body.email, "role": body.role})
    return UserPublic.model_validate(new_user)


class UserRoleUpdate(BaseModel):
    role: Literal["admin", "operator", "viewer"]


@router.patch("/{tenant_id}/users/{user_id}", response_model=UserPublic)
async def update_user_role(
    tenant_id: UUID,
    user_id: UUID,
    body: UserRoleUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> UserPublic:
    if tenant_id != user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="tenant not found")
    target = await session.get(User, user_id)
    if target is None or target.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="user not found")
    if user_id == user.id and body.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="you cannot demote yourself — ask another admin to do it",
        )
    old_role = target.role
    target.role = body.role
    await session.flush()
    await log_audit(session, user_id=user.id, tenant_id=tenant_id,
                    action="user.role_change", target_type="user",
                    target_id=user_id,
                    payload={"from": old_role, "to": body.role})
    return UserPublic.model_validate(target)


@router.delete("/{tenant_id}/users/{user_id}", response_model=OkResponse)
async def delete_user(
    tenant_id: UUID,
    user_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> OkResponse:
    if tenant_id != user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="tenant not found")
    if user_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="you cannot delete your own account while signed in",
        )
    target = await session.get(User, user_id)
    if target is None or target.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="user not found")

    # Refuse if this would leave the tenant with zero admins.
    if target.role == "admin":
        admin_count = (await session.execute(
            select(User).where(
                User.tenant_id == tenant_id,
                User.role == "admin",
            )
        )).scalars().all()
        if len(admin_count) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cannot delete the last remaining admin",
            )

    payload = {"email": target.email, "role": target.role}
    await session.delete(target)
    await session.flush()
    await log_audit(session, user_id=user.id, tenant_id=tenant_id,
                    action="user.delete", target_type="user",
                    target_id=user_id, payload=payload)
    return OkResponse()


# ---------------------------------------------------------------------------
# Audit log read API — admin-only (router already requires_admin)
# ---------------------------------------------------------------------------

class AuditEntry(BaseModel):
    id: int
    ts: str
    user_id: UUID | None
    action: str
    target_type: str | None
    target_id: UUID | None
    payload: dict


@router.get("/{tenant_id}/audit", response_model=list[AuditEntry])
async def list_audit(
    tenant_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    action_prefix: str | None = Query(None, max_length=64),
) -> list[AuditEntry]:
    if tenant_id != user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="tenant not found")
    from ...db.models.ops import AuditLog
    q = select(AuditLog).where(AuditLog.tenant_id == tenant_id)
    if action_prefix:
        q = q.where(AuditLog.action.startswith(action_prefix))
    q = q.order_by(AuditLog.ts.desc()).limit(limit).offset(offset)
    rows = (await session.execute(q)).scalars().all()
    return [
        AuditEntry(
            id=r.id, ts=r.ts.isoformat(),
            user_id=r.user_id, action=r.action,
            target_type=r.target_type, target_id=r.target_id,
            payload=r.payload or {},
        )
        for r in rows
    ]
