"""Auth request / response shapes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str = Field(..., min_length=1, max_length=200)


class TokenPair(BaseModel):
    access_token:        str
    refresh_token:       str
    access_expires_at:   datetime
    refresh_expires_at:  datetime
    token_type:          str = "bearer"


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:        UUID
    tenant_id: UUID
    email:     EmailStr
    role:      str
    created_at: datetime


class LoginResponse(BaseModel):
    tokens: TokenPair
    user:   UserPublic


class RefreshRequest(BaseModel):
    refresh_token: str
