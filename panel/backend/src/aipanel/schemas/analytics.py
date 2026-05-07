"""Analytics response schemas."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class OverviewResponse(BaseModel):
    total_calls:     int
    avg_duration_sec: float
    transfer_rate:   float
    dispo_breakdown: dict[str, int]
    period_start:    date
    period_end:      date


class AgentRollup(BaseModel):
    agent_id:         UUID
    agent_name:       str
    total_calls:      int
    avg_duration_sec: float
    transfer_rate:    float
    dispo_top:        str | None


class AgentRollupResponse(BaseModel):
    rows: list[AgentRollup]


class TimeseriesPoint(BaseModel):
    ts:     datetime
    calls:  int
    transfers: int
    avg_duration_sec: float


class TimeseriesResponse(BaseModel):
    bucket:  str           # "hour" | "day"
    points:  list[TimeseriesPoint]
