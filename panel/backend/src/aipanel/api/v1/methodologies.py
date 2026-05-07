"""GET /api/v1/methodologies — read-only catalog of sales methodologies.

Used by the campaign picker UI to render rich previews. The same data ships
with the worker (mirrored at workers/src/aipanel_worker/methodologies.py)
so the API preview matches what the LLM actually sees at call time.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ...auth.deps import get_current_user
from ...sales_lib import get_methodology, list_methodologies
from ...schemas.methodology import (
    CallStageRead,
    MethodologyDetailRead,
    MethodologyRead,
)

router = APIRouter(prefix="/methodologies", tags=["methodologies"],
                   dependencies=[Depends(get_current_user)])


def _to_read(m) -> MethodologyRead:
    return MethodologyRead(
        key=m["key"], name=m["name"],
        tagline=m["tagline"], when_to_use=m["when_to_use"],
    )


def _to_detail(m) -> MethodologyDetailRead:
    return MethodologyDetailRead(
        key=m["key"], name=m["name"],
        tagline=m["tagline"], when_to_use=m["when_to_use"],
        system_prompt=m["system_prompt"],
        stages=[CallStageRead(**s) for s in m["stages"]],
        priority_signals=list(m["priority_signals"]),
        common_objections=dict(m["common_objections"]),
    )


@router.get("", response_model=list[MethodologyRead])
async def list_all() -> list[MethodologyRead]:
    return [_to_read(m) for m in list_methodologies()]


@router.get("/{key}", response_model=MethodologyDetailRead)
async def get_one(key: str) -> MethodologyDetailRead:
    m = get_methodology(key)
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"unknown methodology: {key}")
    return _to_detail(m)
