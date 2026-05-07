"""ViciDial server registration schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class VicidialServerCreate(BaseModel):
    name:           str        = Field(..., min_length=1, max_length=200)
    asterisk_host:  str        = Field(..., min_length=1, max_length=200)
    asterisk_port:  int        = Field(5038, ge=1, le=65535)
    web_url:        HttpUrl
    ami_user:       str        = Field(..., min_length=1, max_length=128)
    ami_pass:       str        = Field(..., min_length=1, max_length=200)
    web_user_admin: str        = Field(..., min_length=1, max_length=128)
    web_pass:       str        = Field(..., min_length=1, max_length=200)


class VicidialServerUpdate(BaseModel):
    name:           str | None = None
    asterisk_host:  str | None = None
    asterisk_port:  int | None = None
    web_url:        HttpUrl | None = None
    ami_user:       str | None = None
    ami_pass:       str | None = None
    web_user_admin: str | None = None
    web_pass:       str | None = None


class VicidialServerRead(BaseModel):
    """Public view — never expose encrypted credentials."""
    model_config = ConfigDict(from_attributes=True)

    id:             UUID
    tenant_id:      UUID
    name:           str
    asterisk_host:  str
    asterisk_port:  int
    web_url:        str
    ami_user:       str
    web_user_admin: str
    created_at:     datetime


class VicidialTestResult(BaseModel):
    web_login_ok: bool
    web_error:    str | None = None
    ami_ok:       bool       = False
    ami_error:    str | None = None
