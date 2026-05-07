"""Load sentence-transformers model once at startup."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import structlog

from .config import EmbedConfig

log = structlog.get_logger().bind(component="model_loader")


class LoadedModel:
    model: Any
    device: str
    dim: int
    loaded_at: datetime
    name: str


_loaded: LoadedModel | None = None


def _resolve_device(req: str) -> str:
    if req != "auto":
        return req
    if os.environ.get("CUDA_VISIBLE_DEVICES", "").strip():
        try:
            import ctypes
            ctypes.CDLL("libcudart.so")
            return "cuda"
        except OSError:
            pass
    return "cpu"


def load_model(cfg: EmbedConfig) -> LoadedModel:
    global _loaded
    if _loaded is not None:
        return _loaded

    from sentence_transformers import SentenceTransformer

    device = _resolve_device(cfg.device)
    # Prefer the locally-staged model from models.sh; fall back to HF id.
    local = cfg.models_dir / cfg.model.replace("/", "__")
    model_path = str(local) if (local / "config.json").exists() else cfg.model

    log.info("embed_model_loading",
             model=cfg.model, model_path=model_path, device=device)
    m = SentenceTransformer(model_path, device=device)

    out = LoadedModel()
    out.model = m
    out.device = device
    out.dim = int(m.get_sentence_embedding_dimension() or 1024)
    out.loaded_at = datetime.now(timezone.utc)
    out.name = cfg.model
    _loaded = out
    log.info("embed_model_ready", dim=out.dim, device=device)
    return out


def get_loaded() -> LoadedModel | None:
    return _loaded
