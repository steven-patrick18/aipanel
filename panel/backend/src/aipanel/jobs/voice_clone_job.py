"""ARQ job: send a freshly uploaded reference clip to the TTS server."""

from __future__ import annotations

import base64

import structlog

from ..config import get_config
from ..db.session import get_sessionmaker
from ..integrations.tts_client import TTSClient
from ..services import voice_service

log = structlog.get_logger().bind(component="voice_clone_job")


async def voice_clone(
    ctx: dict,
    voice_id: str,
    tenant_id: str,
    name: str,
    ref_text: str,
    audio_b64: str,
    filename: str,
) -> dict:
    """Idempotent — re-running flips the voice back through pending → ready."""
    from uuid import UUID
    cfg = get_config()
    audio_bytes = base64.b64decode(audio_b64)

    log.info("voice_clone_start", voice_id=voice_id,
             bytes=len(audio_bytes), filename=filename)

    async with TTSClient(cfg.tts.endpoint) as tts:
        result = await tts.clone(
            voice_name=name, tenant_id=UUID(tenant_id),
            ref_text=ref_text, audio=audio_bytes, filename=filename,
        )

    sm = get_sessionmaker()
    async with sm() as session:
        if result is None:
            await voice_service.mark_voice_error(session, voice_id=UUID(voice_id))
            await session.commit()
            log.warning("voice_clone_failed", voice_id=voice_id)
            return {"ok": False}
        await voice_service.mark_voice_ready(
            session, voice_id=UUID(voice_id),
            sample_path=result.get("embedding_path", ""),
            embedding_path=result.get("embedding_path", ""),
        )
        await session.commit()

    log.info("voice_clone_done", voice_id=voice_id)
    return {"ok": True, "embedding_path": result.get("embedding_path", "")}
