"""Operational tables: nodes, audit_log, schema_migrations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ARRAY, BigInteger, DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ._helpers import created_at, jsonb_default, uuid_pk


class Node(Base):
    __tablename__ = "nodes"

    id:                Mapped[UUID]            = uuid_pk()
    hostname:          Mapped[str]             = mapped_column(
        Text, nullable=False, unique=True
    )
    role:              Mapped[str]             = mapped_column(
        Enum("primary", "secondary",
             name="node_role", create_type=False),
        nullable=False,
    )
    services:          Mapped[list[str]]       = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}",
    )
    status:            Mapped[str]             = mapped_column(
        Text, nullable=False, default="unknown", server_default="unknown",
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    joined_at:         Mapped[datetime]        = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    drained_at:        Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class NodeJoinToken(Base):
    __tablename__ = "node_join_tokens"

    id:               Mapped[UUID]               = uuid_pk()
    token_hash:       Mapped[str]                = mapped_column(
        Text, nullable=False, unique=True
    )
    role:             Mapped[str]                = mapped_column(Text, nullable=False)
    label:            Mapped[str]                = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    created_by:       Mapped[UUID | None]        = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    created_at:       Mapped[datetime]           = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at:       Mapped[datetime]           = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at:      Mapped[datetime | None]    = mapped_column(
        DateTime(timezone=True)
    )
    consumed_by_node: Mapped[UUID | None]        = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="SET NULL"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id:          Mapped[int]           = mapped_column(BigInteger, primary_key=True)
    ts:          Mapped[datetime]      = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    user_id:     Mapped[UUID | None]   = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    tenant_id:   Mapped[UUID | None]   = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        index=True,
    )
    action:      Mapped[str]           = mapped_column(Text, nullable=False)
    target_type: Mapped[str | None]    = mapped_column(Text)
    target_id:   Mapped[UUID | None]   = mapped_column(PgUUID(as_uuid=True))
    payload:     Mapped[dict]          = jsonb_default(dict)


class SchemaMigration(Base):
    """Mirrors the migration runner's bookkeeping table from prompt 2."""
    __tablename__ = "schema_migrations"

    version:    Mapped[str]      = mapped_column(Text, primary_key=True)
    name:       Mapped[str]      = mapped_column(Text, nullable=False)
    checksum:   Mapped[str]      = mapped_column(Text, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
