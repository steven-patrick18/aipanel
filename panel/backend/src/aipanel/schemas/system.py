"""System / cluster / health schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class ServiceHealth(BaseModel):
    name:    str
    status:  str        # "ok" | "degraded" | "down"
    detail:  str = ""


class SystemHealth(BaseModel):
    overall:  str
    services: list[ServiceHealth]
    checked_at: datetime


class VersionInfo(BaseModel):
    version:    str
    build_time: datetime | None = None


class SafeConfig(BaseModel):
    panel_public_url: str
    sip_listen_port:  int
    llm_model:        str
    stt_model:        str
    tts_backend:      str


class NodeRead(BaseModel):
    id:        UUID
    hostname:  str
    role:      str
    services:  list[str]
    status:    str
    last_heartbeat_at: datetime | None
    joined_at: datetime


class JoinTokenResponse(BaseModel):
    feature_disabled: bool = True
    message:          str  = (
        "Multi-node clustering is not enabled in this build."
    )
