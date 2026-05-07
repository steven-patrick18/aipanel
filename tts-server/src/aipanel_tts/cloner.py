"""HTTP route: POST /v1/tts/clone → register a voice from a reference clip."""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

log = structlog.get_logger().bind(component="cloner")

router = APIRouter()


@router.post("/v1/tts/clone")
async def clone(
    request: Request,
    voice_name: str = Form(..., min_length=1, max_length=200),
    tenant_id: str = Form(..., description="UUID of the tenant"),
    ref_text: str = Form(..., description="transcript of the reference audio"),
    audio: UploadFile = File(..., description="reference audio (WAV preferred)"),
) -> dict:
    state = request.app.state
    backend = state.backend
    voice_store = state.voice_store

    try:
        tenant_uuid = UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="tenant_id must be a UUID") from None

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="empty audio upload")

    # Reserve the voice_id up front so the on-disk path matches the DB row.
    voice_id = voice_store.create(
        tenant_id=tenant_uuid,
        name=voice_name,
        # paths are filled in below via UPDATE — but the simple MVP path
        # is to insert with the predictable filename and let it be.
        sample_path=str(state.cfg.voices_dir),
        embedding_path=str(state.cfg.voices_dir),
    )

    # backend.clone writes the ref.wav + ref_text.txt and returns the path
    # we should consider the embedding for this voice.
    embedding_path = backend.clone(
        voice_id=str(voice_id),
        voice_name=voice_name,
        audio_bytes=audio_bytes,
        ref_text=ref_text,
    )

    log.info("clone_done", voice_id=str(voice_id),
             name=voice_name, embedding_path=str(embedding_path))

    return {
        "voice_id": str(voice_id),
        "voice_name": voice_name,
        "embedding_path": str(embedding_path),
        "status": "ready",
    }


@router.get("/v1/tts/voices")
async def list_voices(request: Request, tenant_id: str | None = None) -> dict:
    state = request.app.state
    voice_store = state.voice_store

    tenant_uuid = None
    if tenant_id:
        try:
            tenant_uuid = UUID(tenant_id)
        except ValueError:
            raise HTTPException(status_code=400,
                                detail="tenant_id must be a UUID") from None

    voices = voice_store.list(tenant_id=tenant_uuid)
    return {
        "voices": [
            {
                "voice_id": str(v.voice_id),
                "tenant_id": str(v.tenant_id),
                "name": v.name,
                "sample_path": v.sample_path,
                "embedding_path": v.embedding_path,
                "status": v.status,
            }
            for v in voices
        ],
    }
