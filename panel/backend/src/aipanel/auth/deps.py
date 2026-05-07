"""FastAPI dependencies for auth.

* ``get_current_user`` — verifies ``Authorization: Bearer <access>`` and loads
  the User row. Raises 401 on any failure.
* ``get_tenant_id`` — convenience accessor for routes that only need the tenant.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models.tenants import User
from ..db.session import get_session
from .denylist import is_denied
from .jwt import InvalidToken, TokenPayload, verify

_bearer = HTTPBearer(auto_error=False)


async def _read_token(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> TokenPayload:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = verify(creds.credentials, expected_type="access")
    except InvalidToken as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    # Denylist check — token revoked via /logout.
    if payload.jti and await is_denied(payload.jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


async def get_current_user(
    payload: Annotated[TokenPayload, Depends(_read_token)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    user = await session.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="user no longer exists")
    if user.tenant_id != payload.tenant_id or user.role != payload.role:
        # Token state diverged from DB — treat as compromised.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="token / user mismatch")
    return user


async def get_tenant_id(
    user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    return user.tenant_id


CurrentUser = Annotated[User, Depends(get_current_user)]
TenantId    = Annotated[UUID, Depends(get_tenant_id)]
