"""Campaign ORM model.

A campaign bundles a sales playbook (persona + script templates, KB binding,
success definition, methodology choice) and a mined few-shot pool that the
worker injects into the system prompt at call time. One campaign can be
shared across many agents/deployments.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ARRAY, DateTime, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ._helpers import created_at, jsonb_default, updated_at, uuid_pk


class Campaign(Base):
    __tablename__ = "campaigns"

    id:          Mapped[UUID]         = uuid_pk()
    tenant_id:   Mapped[UUID]         = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name:        Mapped[str]          = mapped_column(Text, nullable=False)
    description: Mapped[str]          = mapped_column(
        Text, nullable=False, default="", server_default="",
    )
    methodology: Mapped[str]          = mapped_column(
        Enum("spin", "bant", "meddpicc", "consultative", "value_based", "custom",
             name="campaign_methodology", create_type=False),
        nullable=False, default="consultative",
    )
    objective:   Mapped[str]          = mapped_column(
        Text, nullable=False, default="", server_default="",
    )
    success_dispos:  Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False,
        default=lambda: ["QUAL", "XFER"],
        server_default="{QUAL,XFER}",
    )
    persona_template:    Mapped[dict] = jsonb_default(dict)
    script_template:     Mapped[dict] = jsonb_default(dict)
    kb_collection_id:    Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
    )
    # JSON list of {user, agent, score, call_id, mined_at}. See
    # jobs/campaign_mine_job.py for how it's populated.
    few_shot_pool:       Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]",
    )
    few_shot_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    status:      Mapped[str]          = mapped_column(
        Enum("draft", "active", "paused", "archived",
             name="campaign_status", create_type=False),
        nullable=False, default="draft",
    )
    created_at:  Mapped[datetime]     = created_at()
    updated_at:  Mapped[datetime]     = updated_at()
