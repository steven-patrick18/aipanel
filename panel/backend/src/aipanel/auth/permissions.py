"""Role-based access dependencies.

Usage::

    @router.post("/agents", dependencies=[Depends(require_role("admin", "operator"))])
    async def create_agent(...): ...
"""

from __future__ import annotations

from typing import Annotated, Callable

from fastapi import Depends, HTTPException, status

from ..db.models.tenants import User
from .deps import get_current_user

ROLES_ALL    = ("admin", "operator", "viewer")
ROLES_WRITE  = ("admin", "operator")
ROLES_ADMIN  = ("admin",)


def require_role(*roles: str) -> Callable:
    """Return a FastAPI dependency that 403s unless ``user.role in roles``."""
    if not roles:
        raise ValueError("require_role needs at least one role")
    role_set = frozenset(roles)

    async def _dep(
        user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if user.role not in role_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires one of: {sorted(role_set)}",
            )
        return user

    return _dep


require_admin    = require_role(*ROLES_ADMIN)
require_writer   = require_role(*ROLES_WRITE)
require_any_user = require_role(*ROLES_ALL)
