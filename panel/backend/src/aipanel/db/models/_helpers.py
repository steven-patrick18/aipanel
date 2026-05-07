"""Shared SQLAlchemy column helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column


def uuid_pk() -> Mapped[UUID]:
    """``uuid PRIMARY KEY DEFAULT gen_random_uuid()`` mirrored in Python."""
    return mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )


def created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


def updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


def jsonb_default(default_obj: Any) -> Mapped[Any]:
    return mapped_column(
        JSONB,
        nullable=False,
        default=lambda: default_obj() if callable(default_obj) else dict(default_obj),
        server_default="{}",
    )
