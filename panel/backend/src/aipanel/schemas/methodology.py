"""Methodology catalog schemas — read-only for the panel UI."""

from __future__ import annotations

from pydantic import BaseModel


class CallStageRead(BaseModel):
    name:            str
    goal:            str
    success_markers: list[str]


class MethodologyRead(BaseModel):
    """Lightweight catalog entry for the picker UI."""
    key:         str
    name:        str
    tagline:     str
    when_to_use: str


class MethodologyDetailRead(MethodologyRead):
    """Full detail — what an operator sees in the picker preview."""
    system_prompt:     str
    stages:            list[CallStageRead]
    priority_signals:  list[str]
    common_objections: dict[str, str]
