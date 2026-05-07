"""System endpoints — health, version, safe config snapshot, backup trigger."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends

from ...auth.deps import CurrentUser
from ...auth.permissions import require_admin
from ...config import get_config
from ...integrations.llm_client import LLMClient
from ...integrations.session_mgr_client import SessionMgrClient
from ...integrations.stt_client import STTClient
from ...integrations.tts_client import TTSClient
from ...jobs.arq_worker import get_arq
from ...schemas.common import OkResponse
from ...schemas.system import SafeConfig, ServiceHealth, SystemHealth, VersionInfo

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/version", response_model=VersionInfo)
async def version() -> VersionInfo:
    from ... import __version__ as v
    return VersionInfo(version=v)


@router.get("/health", response_model=SystemHealth)
async def system_health(_user: CurrentUser) -> SystemHealth:
    cfg = get_config()
    services: list[ServiceHealth] = []

    # Probe each service in parallel.
    llm = LLMClient(cfg.llm.endpoint.replace("/v1", "").rstrip("/"))
    stt = STTClient(cfg.stt.endpoint)
    try:
        async with TTSClient(cfg.tts.endpoint) as tts:
            llm_h, stt_h, tts_h = await asyncio.gather(
                llm.health(), stt.health(), tts.health(),
            )
    finally:
        await llm.aclose()
        await stt.aclose()

    services.append(ServiceHealth(
        name="llm",
        status="ok" if llm_h and llm_h.get("status") == "ok" else "degraded",
        detail=str((llm_h or {}).get("status", "unreachable")),
    ))
    services.append(ServiceHealth(
        name="stt",
        status="ok" if stt_h and stt_h.get("status") == "ok" else "degraded",
        detail=str((stt_h or {}).get("status", "unreachable")),
    ))
    services.append(ServiceHealth(
        name="tts",
        status="ok" if tts_h and tts_h.get("status") == "ok" else "degraded",
        detail=str((tts_h or {}).get("status", "unreachable")),
    ))

    overall = "ok" if all(s.status == "ok" for s in services) else "degraded"
    return SystemHealth(
        overall=overall, services=services,
        checked_at=datetime.now(timezone.utc),
    )


@router.get("/config", response_model=SafeConfig)
async def get_safe_config(_user: CurrentUser) -> SafeConfig:
    cfg = get_config()
    return SafeConfig(
        panel_public_url=cfg.panel.public_url,
        sip_listen_port=cfg.sip.listen_port,
        llm_model=cfg.llm.model,
        stt_model=cfg.stt.model,
        tts_backend=cfg.tts.provider,
    )


@router.post("/backup-now", response_model=OkResponse,
             dependencies=[Depends(require_admin)])
async def backup_now(arq: Annotated[ArqRedis, Depends(get_arq)]) -> OkResponse:
    await arq.enqueue_job("nightly_backup")
    return OkResponse()
