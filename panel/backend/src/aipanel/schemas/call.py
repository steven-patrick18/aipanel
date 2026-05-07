"""Call + transcript schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CallSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:              UUID
    deployment_id:   UUID
    vici_uniqueid:   str
    vici_lead_id:    str | None
    phone_number:    str | None
    started_at:      datetime
    ended_at:        datetime | None
    duration_sec:    int | None
    outcome:         str | None
    dispo_code:      str | None
    transfer_target: str | None


class CallEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:         UUID
    call_id:    UUID
    ts:         datetime
    event_type: str
    payload:    dict[str, Any]


class CallTranscript(BaseModel):
    """Flattened per-turn view derived from call_events."""
    call_id: UUID
    turns:   list["TranscriptTurn"]


class TranscriptTurn(BaseModel):
    ts:     datetime
    role:   str        # "user" | "agent" | "system"
    text:   str
    extra:  dict[str, Any] = {}


class RecordingUrl(BaseModel):
    url:        str
    expires_in: int = 3600
