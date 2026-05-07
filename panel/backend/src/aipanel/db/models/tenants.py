"""Tenant + User ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base
from ._helpers import created_at, jsonb_default, uuid_pk


class Tenant(Base):
    __tablename__ = "tenants"

    id:         Mapped[UUID]              = uuid_pk()
    name:       Mapped[str]               = mapped_column(Text, nullable=False)
    settings:   Mapped[dict]              = jsonb_default(dict)
    created_at: Mapped[datetime]          = created_at()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="users_email_key"),)

    id:            Mapped[UUID]    = uuid_pk()
    tenant_id:     Mapped[UUID]    = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    email:         Mapped[str]     = mapped_column(Text, nullable=False)
    password_hash: Mapped[str]     = mapped_column(Text, nullable=False)
    role:          Mapped[str]     = mapped_column(
        Enum("admin", "operator", "viewer", name="user_role", create_type=False),
        nullable=False,
    )
    created_at:    Mapped[datetime] = created_at()

    tenant: Mapped[Tenant] = relationship(lazy="joined")
