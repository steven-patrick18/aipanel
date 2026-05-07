"""Tenant + user invite schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class TenantCreate(BaseModel):
    name:     str = Field(..., min_length=1, max_length=200)
    settings: dict[str, Any] = Field(default_factory=dict)


class TenantUpdate(BaseModel):
    name:     str | None = None
    settings: dict[str, Any] | None = None


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:         UUID
    name:       str
    settings:   dict[str, Any]
    created_at: datetime


class UserInvite(BaseModel):
    email:    EmailStr
    role:     Literal["admin", "operator", "viewer"]
    password: str = Field(..., min_length=8, max_length=200)
