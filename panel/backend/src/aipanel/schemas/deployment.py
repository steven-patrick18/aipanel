"""Deployment schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DeploymentCreate(BaseModel):
    agent_id:                  UUID
    vicidial_server_id:        UUID
    vici_user:                 str        = Field(..., min_length=1, max_length=128)
    vici_pass:                 str        = Field(..., min_length=1, max_length=200)
    phone_login:               str        = Field(..., min_length=1, max_length=64)
    phone_pass:                str        = Field(..., min_length=1, max_length=200)
    # ``campaign_id`` here = ViciDial campaign *code* (e.g. "SOLAR").
    # ``aipanel_campaign_id`` = link to an aipanel campaigns row (UUID).
    campaign_id:               str        = Field(..., min_length=1, max_length=64)
    aipanel_campaign_id:       UUID | None = None
    allowed_transfer_ingroups: list[str]  = Field(default_factory=list)
    dispo_mapping:             dict[str, Any] = Field(default_factory=dict)


class DeploymentUpdate(BaseModel):
    vici_user:                 str | None        = None
    vici_pass:                 str | None        = None
    phone_login:               str | None        = None
    phone_pass:                str | None        = None
    campaign_id:               str | None        = None
    aipanel_campaign_id:       UUID | None       = None
    allowed_transfer_ingroups: list[str] | None  = None
    dispo_mapping:             dict[str, Any] | None = None


class DeploymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:                        UUID
    tenant_id:                 UUID
    agent_id:                  UUID
    vicidial_server_id:        UUID
    vici_user:                 str
    phone_login:               str
    campaign_id:               str
    aipanel_campaign_id:       UUID | None       = None
    allowed_transfer_ingroups: list[str]
    dispo_mapping:             dict[str, Any]
    status:                    str
    last_heartbeat_at:         datetime | None
    created_at:                datetime
    updated_at:                datetime
