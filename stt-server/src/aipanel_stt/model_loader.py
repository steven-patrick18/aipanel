"""Load + cache the faster-whisper model and the silero VAD ONNX session.

Both load once at app startup. We pick the device automatically when
``device == "auto"``: CUDA if visible to the process, else CPU. The compute
type is honoured as configured but downgraded to ``int8`` on CPU to keep
real-time-factor below 1 on the smoke-test box.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from .config import STTConfig

log = structlog.get_logger().bind(component="model_loader")


class LoadedModels:
    whisper: Any                 # faster_whisper.WhisperModel
    vad_iterator_factory: Any    # callable returning a fresh VADIterator
    device: str
    compute_type: str
    loaded_at: datetime


_models: LoadedModels | None = None


def _resolve_device(requested: str) -> str:
    if requested != "auto":
        return requested
    # faster-whisper detects CUDA via CTranslate2; we approximate by checking
    # CUDA_VISIBLE_DEVICES + nvidia-smi presence to avoid importing torch.
    if os.environ.get("CUDA_VISIBLE_DEVICES", "").strip() == "":
        return "cpu"
    try:
        import ctypes
        ctypes.CDLL("libcudart.so")
        return "cuda"
    except OSError:
        return "cpu"


def _resolve_compute_type(device: str, requested: str) -> str:
    if device == "cpu" and requested in ("float16", "int8_float16"):
        return "int8"
    return requested


def _resolve_model_path(cfg: STTConfig) -> str:
    """Prefer the local copy installed by models.sh, else fall back to HF id."""
    local = cfg.models_dir / cfg.model
    if (local / "model.bin").exists() or (local / "tokenizer.json").exists():
        return str(local)
    return cfg.model


def load_models(cfg: STTConfig) -> LoadedModels:
    """Load once at startup. Subsequent calls return the cached instance."""
    global _models
    if _models is not None:
        return _models

    # Defer heavy imports until called — keeps `python -m aipanel_stt.main --help`
    # fast and lets unit tests stub pieces in.
    from faster_whisper import WhisperModel
    from silero_vad import VADIterator, load_silero_vad

    device = _resolve_device(cfg.device)
    compute_type = _resolve_compute_type(device, cfg.compute_type)
    model_path = _resolve_model_path(cfg)

    log.info("whisper_loading",
             model=cfg.model, model_path=model_path,
             device=device, compute_type=compute_type)
    whisper = WhisperModel(
        model_path,
        device=device,
        compute_type=compute_type,
    )

    log.info("silero_vad_loading")
    vad_model = load_silero_vad()

    def _make_iterator():
        # silero-vad's VADIterator is single-call-stateful; one per stream.
        return VADIterator(
            vad_model,
            threshold=cfg.vad_threshold,
            sampling_rate=16000,
            min_silence_duration_ms=cfg.vad_min_silence_ms,
        )

    out = LoadedModels()
    out.whisper = whisper
    out.vad_iterator_factory = _make_iterator
    out.device = device
    out.compute_type = compute_type
    out.loaded_at = datetime.now(timezone.utc)
    _models = out
    log.info("stt_models_ready",
             device=device, compute_type=compute_type,
             model=cfg.model, loaded_at=out.loaded_at.isoformat())
    return out


def get_models() -> LoadedModels | None:
    """Returns the loaded models or None if startup hasn't completed yet."""
    return _models
