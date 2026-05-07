"""Agent + Voice + Knowledge Base ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ._helpers import created_at, jsonb_default, updated_at, uuid_pk


class Voice(Base):
    __tablename__ = "voices"

    id:             Mapped[UUID]        = uuid_pk()
    tenant_id:      Mapped[UUID]        = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name:           Mapped[str]         = mapped_column(Text, nullable=False)
    sample_path:    Mapped[str | None]  = mapped_column(Text)
    embedding_path: Mapped[str | None]  = mapped_column(Text)
    status:         Mapped[str]         = mapped_column(
        Enum("pending", "training", "ready", "error",
             name="voice_status", create_type=False),
        nullable=False, default="pending",
    )
    created_at:     Mapped[datetime]    = created_at()


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id:              Mapped[UUID]       = uuid_pk()
    tenant_id:       Mapped[UUID]       = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name:            Mapped[str]        = mapped_column(Text, nullable=False)
    description:     Mapped[str | None] = mapped_column(Text)
    embedding_model: Mapped[str]        = mapped_column(Text, nullable=False)
    created_at:      Mapped[datetime]   = created_at()


class KbDocument(Base):
    __tablename__ = "kb_documents"

    id:           Mapped[UUID]       = uuid_pk()
    kb_id:        Mapped[UUID]       = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    filename:     Mapped[str]        = mapped_column(Text, nullable=False)
    content_hash: Mapped[str]        = mapped_column(Text, nullable=False)
    chunk_count:  Mapped[int]        = mapped_column(Integer, nullable=False, default=0)
    status:       Mapped[str]        = mapped_column(
        Enum("pending", "processing", "ready", "error",
             name="kb_doc_status", create_type=False),
        nullable=False, default="pending",
    )
    created_at:   Mapped[datetime]   = created_at()


class Agent(Base):
    __tablename__ = "agents"

    id:               Mapped[UUID]              = uuid_pk()
    tenant_id:        Mapped[UUID]              = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name:             Mapped[str]               = mapped_column(Text, nullable=False)
    persona:          Mapped[dict]              = jsonb_default(dict)
    voice_id:         Mapped[UUID | None]       = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("voices.id", ondelete="SET NULL"),
    )
    language:         Mapped[str]               = mapped_column(
        Text, nullable=False, default="en", server_default="en",
    )
    script:               Mapped[dict]            = jsonb_default(dict)
    scenario_tree:        Mapped[dict]            = jsonb_default(dict)
    training_recordings:  Mapped[list]            = jsonb_default(list)
    kb_collection_id: Mapped[UUID | None]       = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
    )
    campaign_id:      Mapped[UUID | None]       = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        index=True,
    )
    status:           Mapped[str]               = mapped_column(
        Enum("draft", "ready", "archived",
             name="agent_status", create_type=False),
        nullable=False, default="draft",
    )
    created_at:       Mapped[datetime]          = created_at()
    updated_at:       Mapped[datetime]          = updated_at()
