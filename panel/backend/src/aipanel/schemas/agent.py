"""Agent CRUD schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .agent_dsl import Persona, ScenarioTree, Script


class AgentCreate(BaseModel):
    name:             str = Field(..., min_length=1, max_length=200)
    persona:          Persona
    script:           Script
    scenario_tree:    ScenarioTree = Field(default_factory=ScenarioTree)
    voice_id:         UUID | None  = None
    language:         str          = "en"
    kb_collection_id: UUID | None  = None
    campaign_id:      UUID | None  = None


class AgentUpdate(BaseModel):
    name:             str | None        = None
    persona:          Persona | None    = None
    script:           Script | None     = None
    scenario_tree:    ScenarioTree | None = None
    voice_id:         UUID | None       = None
    language:         str | None        = None
    kb_collection_id: UUID | None       = None
    campaign_id:      UUID | None       = None


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:                  UUID
    tenant_id:           UUID
    name:                str
    persona:             dict[str, Any]
    script:              dict[str, Any]
    scenario_tree:       dict[str, Any]
    training_recordings: list[dict[str, Any]] = Field(default_factory=list)
    voice_id:            UUID | None
    language:            str
    kb_collection_id:    UUID | None
    campaign_id:         UUID | None       = None
    status:              str
    created_at:          datetime
    updated_at:          datetime


class AgentTestCallRequest(BaseModel):
    phone_number: str = Field(..., min_length=4, max_length=32)
    deployment_id: UUID | None = None
    """If omitted, the API picks the first running deployment for this agent."""


# ---------------------------------------------------------------------------
# Training recordings — operator-uploaded audio. The transcription
# pipeline turns these into few-shot examples for the agent.
# ---------------------------------------------------------------------------


class TrainingRecordingRead(BaseModel):
    id:           str
    agent_id:     UUID
    filename:     str
    content_type: str
    size_bytes:   int
    label:        str = ""
    status:       str            # "queued" | "transcribing" | "ready" | "error"
    transcript:   str | None = None
    uploaded_at:  datetime
    uploaded_by:  UUID | None = None
