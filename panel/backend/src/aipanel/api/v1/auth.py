"""POST /api/v1/auth/{login,refresh,logout} + GET /me."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.denylist import deny as deny_jti
from ...auth.deps import CurrentUser, _read_token
from ...auth.jwt import (
    InvalidToken,
    TokenPayload,
    issue_access,
    issue_refresh,
    verify,
    verify_password,
)
from ...db.models.tenants import User
from ...db.session import get_session
from ...schemas.auth import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    TokenPair,
    UserPublic,
)
from ...schemas.common import OkResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _make_token_pair(user: User) -> TokenPair:
    access, access_exp = issue_access(
        user_id=user.id, tenant_id=user.tenant_id, role=user.role,
    )
    refresh, refresh_exp = issue_refresh(
        user_id=user.id, tenant_id=user.tenant_id, role=user.role,
    )
    return TokenPair(
        access_token=access, refresh_token=refresh,
        access_expires_at=access_exp, refresh_expires_at=refresh_exp,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LoginResponse:
    row = await session.execute(
        select(User).where(User.email == body.email.lower())
    )
    user = row.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        # Identical message both branches → no user-enumeration.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="invalid credentials")
    return LoginResponse(
        tokens=_make_token_pair(user),
        user=UserPublic.model_validate(user),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    body: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenPair:
    try:
        payload = verify(body.refresh_token, expected_type="refresh")
    except InvalidToken as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=f"invalid refresh: {exc}") from exc
    user = await session.get(User, payload.user_id)
    if user is None or user.tenant_id != payload.tenant_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="user gone or tenant mismatch")
    return _make_token_pair(user)


@router.post("/logout", response_model=OkResponse)
async def logout(
    payload: Annotated[TokenPayload, Depends(_read_token)],
) -> OkResponse:
    """Add the access token's jti to the Redis denylist with TTL = remaining
    lifetime. Subsequent requests with this token return 401."""
    if payload.jti:
        await deny_jti(payload.jti, int(payload.expires_at.timestamp()))
    return OkResponse()


@router.get("/me", response_model=UserPublic)
async def me(user: CurrentUser) -> UserPublic:
    return UserPublic.model_validate(user)
