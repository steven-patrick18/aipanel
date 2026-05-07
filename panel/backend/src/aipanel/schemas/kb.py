"""Knowledge base schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class KbCreate(BaseModel):
    name:            str        = Field(..., min_length=1, max_length=200)
    description:     str | None = None
    embedding_model: str        = "BAAI/bge-base-en-v1.5"


class KbRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:              UUID
    tenant_id:       UUID
    name:            str
    description:     str | None
    embedding_model: str
    created_at:      datetime


class KbDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:           UUID
    kb_id:        UUID
    filename:     str
    content_hash: str
    chunk_count:  int
    status:       str
    created_at:   datetime


class KbSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    limit: int = Field(5, ge=1, le=20)


class KbSearchHit(BaseModel):
    chunk_text: str
    score:      float
    document_id: UUID | None = None


class KbSearchResponse(BaseModel):
    hits: list[KbSearchHit]
