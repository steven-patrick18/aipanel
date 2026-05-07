"""Voice + cloning schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class VoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:             UUID
    tenant_id:      UUID
    name:           str
    sample_path:    str | None
    embedding_path: str | None
    status:         str
    created_at:     datetime


class VoiceCreateForm(BaseModel):
    """Used as a body model alongside the multipart audio upload."""
    name:     str = Field(..., min_length=1, max_length=200)
    ref_text: str = Field(..., min_length=1, max_length=2000)


class VoicePreviewRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
