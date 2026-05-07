"""Strongly-typed Persona / Script / Scenario models.

These also describe the LLM tool definitions: when an agent's
``ScenarioTree`` references ``transfer`` / ``dispose`` / ``callback``, the
worker exposes the corresponding tool to the LLM.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------

class Persona(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name:        str
    age_range:   Literal["20-30", "30-40", "40-50", "50+"]
    gender:      Literal["female", "male", "neutral"]
    accent:      str
    backstory:   str
    description: str = ""
    guidelines:  str = ""
    disclosure_response: str = (
        "I'm an AI assistant calling on behalf of the team. "
        "I can answer questions, take requests, and connect you to a human."
    )


# ---------------------------------------------------------------------------
# Script
# ---------------------------------------------------------------------------

class ScriptSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id:                          str
    title:                       str
    content:                     str
    expected_response_keywords:  list[str] = Field(default_factory=list)


class Objection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id:       str
    trigger:  str
    response: str


class Script(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opening_variants: list[str] = Field(..., min_length=1, max_length=20)
    sections:         list[ScriptSection] = Field(default_factory=list)
    closing:          str
    objections:       list[Objection] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Scenario tree
# ---------------------------------------------------------------------------

ConditionWhen = Literal["intent_detected", "keyword_match", "sentiment", "custom"]
ActionType    = Literal["transfer", "dispose", "callback", "continue"]


class ScenarioCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    when:       ConditionWhen
    expression: str


class ScenarioAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type:       ActionType
    parameters: dict[str, Any] = Field(default_factory=dict)


class ScenarioRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id:        str
    name:      str
    condition: ScenarioCondition
    action:    ScenarioAction
    priority:  int = 0


class ScenarioTree(BaseModel):
    """Persisted JSONB on the agent.

    The visual builder writes ``{rules, graph}`` where ``rules`` is the
    compiled rule list the worker consumes, and ``graph`` is the raw
    nodes+edges so the canvas can be re-hydrated. Earlier callers
    (CLI / API direct) write the strict ``rules`` shape only. We accept
    both — the backend doesn't interpret these structures, it just
    round-trips them, so we keep validation loose intentionally.
    """
    model_config = ConfigDict(extra="allow")

    rules: list[Any] = Field(default_factory=list)
    graph: dict[str, Any] | None = None
