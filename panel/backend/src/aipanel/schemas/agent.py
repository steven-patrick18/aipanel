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

    id:               UUID
    tenant_id:        UUID
    name:             str
    persona:          dict[str, Any]
    script:           dict[str, Any]
    scenario_tree:    dict[str, Any]
    training_examples: list[dict[str, Any]] = Field(default_factory=list)
    voice_id:         UUID | None
    language:         str
    kb_collection_id: UUID | None
    campaign_id:      UUID | None       = None
    status:           str
    created_at:       datetime
    updated_at:       datetime


class AgentTestCallRequest(BaseModel):
    phone_number: str = Field(..., min_length=4, max_length=32)
    deployment_id: UUID | None = None
    """If omitted, the API picks the first running deployment for this agent."""


# ---------------------------------------------------------------------------
# Training examples — operator-curated few-shot examples per agent.
# ---------------------------------------------------------------------------


class TrainingExampleCreate(BaseModel):
    """A manually-typed `{user, agent}` pair an operator wants the AI to imitate."""
    user: str = Field(..., min_length=1, max_length=4000)
    agent: str = Field(..., min_length=1, max_length=4000)
    notes: str = Field("", max_length=2000)


class TrainingExampleRead(BaseModel):
    id: str
    kind: str                              # "manual" | "call"
    user: str
    agent: str
    notes: str = ""
    call_id: UUID | None = None
    recording_path: str | None = None
    added_at: datetime
    added_by: UUID | None = None


class CallMarkExemplarRequest(BaseModel):
    agent_id: UUID | None = None
    """If omitted, uses the agent linked to this call's deployment."""
    user_turn: str = Field(..., min_length=1, max_length=4000)
    agent_turn: str = Field(..., min_length=1, max_length=4000)
    notes: str = Field("", max_length=2000)
