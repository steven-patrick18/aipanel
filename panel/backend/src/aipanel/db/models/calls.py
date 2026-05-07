"""Call + CallEvent ORM models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, PrimaryKeyConstraint, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ._helpers import created_at, jsonb_default, uuid_pk


class Call(Base):
    __tablename__ = "calls"

    id:              Mapped[UUID]               = uuid_pk()
    deployment_id:   Mapped[UUID]               = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("deployments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    vici_uniqueid:   Mapped[str]                = mapped_column(
        Text, nullable=False, unique=True
    )
    vici_lead_id:    Mapped[str | None]         = mapped_column(Text)
    phone_number:    Mapped[str | None]         = mapped_column(Text)
    started_at:      Mapped[datetime]           = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at:        Mapped[datetime | None]    = mapped_column(DateTime(timezone=True))
    duration_sec:    Mapped[int | None]         = mapped_column(Integer)
    outcome:         Mapped[str | None]         = mapped_column(Text)
    dispo_code:      Mapped[str | None]         = mapped_column(Text)
    transfer_target: Mapped[str | None]         = mapped_column(Text)
    transcript_path: Mapped[str | None]         = mapped_column(Text)
    recording_path:  Mapped[str | None]         = mapped_column(Text)
    campaign_id:     Mapped[UUID | None]        = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        index=True,
    )


class CallEvent(Base):
    """Partitioned by month on ``ts`` in the underlying table.

    SQLAlchemy doesn't manage the partition layout — that lives in
    001_initial.sql. We treat the parent table as a normal table for
    insert/select; partition routing is transparent.
    """
    __tablename__ = "call_events"
    __table_args__ = (
        PrimaryKeyConstraint("id", "ts", name="call_events_pkey"),
        # call_id FK + idx_call_events_call_ts already in the SQL migration.
        {"info": {"is_partitioned": True}},
    )

    id:         Mapped[UUID]     = mapped_column(
        PgUUID(as_uuid=True),
        nullable=False,
    )
    call_id:    Mapped[UUID]     = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
    )
    ts:         Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    event_type: Mapped[str]      = mapped_column(Text, nullable=False)
    payload:    Mapped[dict]     = jsonb_default(dict)
