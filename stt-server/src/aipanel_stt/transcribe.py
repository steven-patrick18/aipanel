"""One-shot REST transcribe endpoint.

The handler accepts a multipart upload of any audio container that
soundfile can read (WAV, FLAC, OGG). We resample to 16 kHz mono float32
in-process — workers should already send 16 kHz to keep this cheap.
"""

from __future__ import annotations

import io

import numpy as np
import soundfile as sf
import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .model_loader import get_models

log = structlog.get_logger().bind(component="transcribe")

router = APIRouter()


def _to_mono16k_f32(audio: np.ndarray, sr: int) -> np.ndarray:
    """Mix down to mono and resample to 16 kHz, returning float32 in [-1, 1]."""
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    if audio.dtype != np.float32:
        # soundfile delivers float in [-1, 1] already when dtype="float32",
        # but be defensive in case the caller subset-read with a different dtype.
        if np.issubdtype(audio.dtype, np.integer):
            max_val = float(np.iinfo(audio.dtype).max)
            audio = audio.astype(np.float32) / max_val
        else:
            audio = audio.astype(np.float32)
    if sr != 16000:
        # Lightweight linear resample. faster-whisper internally handles
        # resampling too; we do it here to keep the wire format predictable
        # and to avoid surprises with very-low-rate uploads.
        ratio = 16000 / sr
        new_len = int(round(audio.shape[0] * ratio))
        audio = np.interp(
            np.linspace(0.0, audio.shape[0], new_len, endpoint=False),
            np.arange(audio.shape[0]),
            audio,
        ).astype(np.float32)
    return audio


@router.post("/v1/stt/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    language: str = Form("en"),
    beam_size: int = Form(5),
) -> dict:
    """Read the upload, transcribe synchronously, return JSON."""
    models = get_models()
    if models is None:
        raise HTTPException(status_code=503, detail="model not yet loaded")

    raw = await audio.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty audio upload")
    try:
        data, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
    except Exception as exc:
        raise HTTPException(status_code=400,
                            detail=f"unreadable audio: {exc}") from exc

    pcm = _to_mono16k_f32(data, sr)
    if pcm.size == 0:
        raise HTTPException(status_code=400, detail="audio decoded to zero samples")

    duration_ms = int(round(pcm.size / 16.0))   # samples / 16 = ms at 16 kHz

    # Empty / "auto" language → faster-whisper detects per call. Costs ~50 ms
    # of extra inference but unlocks the multilingual large-v3 vocabulary.
    lang_arg = None if (not language or language == "auto") else language
    segments_iter, info = models.whisper.transcribe(
        pcm,
        language=lang_arg,
        beam_size=beam_size,
        vad_filter=False,             # caller already gated; we just transcribe
    )
    segments = list(segments_iter)
    text = "".join(s.text for s in segments).strip()

    log.info("transcribe_done",
             chars=len(text), segments=len(segments),
             duration_ms=duration_ms,
             detected_language=info.language)

    return {
        "text": text,
        "language": info.language,
        "duration_ms": duration_ms,
        "segments": [
            {"start_ms": int(s.start * 1000),
             "end_ms":   int(s.end * 1000),
             "text":     s.text}
            for s in segments
        ],
    }
