"""Campaign schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CampaignStatus      = Literal["draft", "active", "paused", "archived"]
CampaignMethodology = Literal[
    "spin", "bant", "meddpicc", "consultative", "value_based", "custom",
]


class CampaignCreate(BaseModel):
    name:             str = Field(..., min_length=1, max_length=200)
    description:      str = ""
    methodology:      CampaignMethodology = "consultative"
    objective:        str = ""
    success_dispos:   list[str] = Field(default_factory=lambda: ["QUAL", "XFER"])
    persona_template: dict[str, Any] = Field(default_factory=dict)
    script_template:  dict[str, Any] = Field(default_factory=dict)
    kb_collection_id: UUID | None = None


class CampaignUpdate(BaseModel):
    name:             str | None = None
    description:      str | None = None
    methodology:      CampaignMethodology | None = None
    objective:        str | None = None
    success_dispos:   list[str] | None = None
    persona_template: dict[str, Any] | None = None
    script_template:  dict[str, Any] | None = None
    kb_collection_id: UUID | None = None
    status:           CampaignStatus | None = None


class CampaignRead(BaseModel):
    """Lightweight read — no template / few-shot bodies (those are in Detail)."""
    model_config = ConfigDict(from_attributes=True)

    id:                  UUID
    tenant_id:           UUID
    name:                str
    description:         str
    methodology:         str
    objective:           str
    success_dispos:      list[str]
    kb_collection_id:    UUID | None
    status:              str
    created_at:          datetime
    updated_at:          datetime
    few_shot_updated_at: datetime | None
    few_shot_count:      int = 0


class FewShotExample(BaseModel):
    """One mined turn pair from a successful call."""
    user:     str
    agent:    str
    score:    float
    call_id:  str
    mined_at: datetime


class CampaignReadDetail(CampaignRead):
    """Full read — includes template payloads + few-shot pool."""
    persona_template: dict[str, Any] = Field(default_factory=dict)
    script_template:  dict[str, Any] = Field(default_factory=dict)
    few_shot_pool:    list[FewShotExample] = Field(default_factory=list)


class CampaignMetrics(BaseModel):
    campaign_id:      UUID
    period_days:      int
    total_calls:      int
    successful_calls: int
    conversion_rate:  float
    by_dispo:         dict[str, int]
    avg_duration_sec: float
