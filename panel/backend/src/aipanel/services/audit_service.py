"""Single helper to write rows into ``audit_log``.

Called from every mutation route. Failures are swallowed + logged so an
audit-DB hiccup never breaks the user's primary action.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models.ops import AuditLog

log = structlog.get_logger().bind(component="audit")


async def log_audit(
    session: AsyncSession,
    *,
    user_id: UUID | None,
    tenant_id: UUID | None,
    action: str,
    target_type: str | None = None,
    target_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    try:
        session.add(AuditLog(
            user_id=user_id,
            tenant_id=tenant_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload=payload or {},
        ))
        await session.flush()
    except Exception as exc:                                 # pragma: no cover
        log.exception("audit_write_failed", action=action, error=str(exc))
