"""Pydantic models shared across the SIP service."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SipAccountModel(BaseModel):
    """A single Asterisk SIP account that aipanel REGISTERs against."""

    model_config = ConfigDict(frozen=False)

    deployment_id: UUID
    phone_login: str
    phone_pass: str               # decrypted in-memory only
    asterisk_host: str
    asterisk_port: int = 5060

    def __str__(self) -> str:    # for log lines, never include password
        return f"{self.phone_login}@{self.asterisk_host}:{self.asterisk_port}"


class CallContext(BaseModel):
    """Per-call metadata shared with the worker over the unix socket."""

    model_config = ConfigDict(frozen=False)

    call_id: UUID                 # SIP-side UUID, distinct from vici_uniqueid
    deployment_id: UUID
    account_login: str
    socket_path: str

    # Headers extracted from the incoming INVITE.
    vici_lead_id: str | None = None
    vici_uniqueid: str | None = None
    vici_campaign: str | None = None
    vici_phone: str | None = None
    p_asserted_identity: str | None = None

    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
