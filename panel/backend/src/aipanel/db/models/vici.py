"""ViciDial server + Deployment ORM models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ARRAY, DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base
from ._helpers import created_at, jsonb_default, updated_at, uuid_pk


class VicidialServer(Base):
    __tablename__ = "vicidial_servers"

    id:                 Mapped[UUID]    = uuid_pk()
    tenant_id:          Mapped[UUID]    = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name:               Mapped[str]     = mapped_column(Text, nullable=False)
    asterisk_host:      Mapped[str]     = mapped_column(Text, nullable=False)
    asterisk_port:      Mapped[int]     = mapped_column(
        Integer, nullable=False, default=5038, server_default="5038",
    )
    web_url:            Mapped[str]     = mapped_column(Text, nullable=False)
    ami_user:           Mapped[str]     = mapped_column(Text, nullable=False)
    ami_pass_encrypted: Mapped[str]     = mapped_column(Text, nullable=False)
    web_user_admin:     Mapped[str]     = mapped_column(Text, nullable=False)
    web_pass_encrypted: Mapped[str]     = mapped_column(Text, nullable=False)
    created_at:         Mapped[datetime] = created_at()


class Deployment(Base):
    __tablename__ = "deployments"

    id:                        Mapped[UUID]              = uuid_pk()
    tenant_id:                 Mapped[UUID]              = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_id:                  Mapped[UUID]              = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    vicidial_server_id:        Mapped[UUID]              = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("vicidial_servers.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    vici_user:                 Mapped[str]               = mapped_column(Text, nullable=False)
    vici_pass_encrypted:       Mapped[str]               = mapped_column(Text, nullable=False)
    phone_login:               Mapped[str]               = mapped_column(Text, nullable=False)
    phone_pass_encrypted:      Mapped[str]               = mapped_column(Text, nullable=False)
    campaign_id:               Mapped[str]               = mapped_column(Text, nullable=False)
    allowed_transfer_ingroups: Mapped[list[str]]         = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}",
    )
    dispo_mapping:             Mapped[dict]              = jsonb_default(dict)
    status:                    Mapped[str]               = mapped_column(
        Enum("stopped", "starting", "running", "error",
             name="deployment_status", create_type=False),
        nullable=False, default="stopped",
    )
    last_heartbeat_at:         Mapped[datetime | None]   = mapped_column(
        DateTime(timezone=True)
    )
    # Collision guard: the existing ``campaign_id`` column is the ViciDial
    # campaign *code* (text). This is the link to an aipanel ``campaigns``
    # row — a different concept.
    aipanel_campaign_id:       Mapped[UUID | None]       = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        index=True,
    )
    created_at:                Mapped[datetime]          = created_at()
    updated_at:                Mapped[datetime]          = updated_at()
