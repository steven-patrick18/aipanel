"""Config loader — reads [stt] from /etc/aipanel/aipanel.conf."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

CONFIG_PATH = Path(os.environ.get("AIPANEL_CONF", "/etc/aipanel/aipanel.conf"))
SECRETS_PATH = Path(os.environ.get("AIPANEL_SECRETS", "/etc/aipanel/secrets.env"))

DEFAULT_MODELS_DIR = Path("/var/lib/aipanel/models/stt")


class STTConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    listen_host: str = "127.0.0.1"
    listen_port: int = 8002

    # Model.
    model: str = "large-v3"
    language: str = "en"
    device: str = "auto"             # auto | cuda | cpu
    compute_type: str = "float16"    # float16 | int8_float16 | int8 | float32
    models_dir: Path = Field(default=DEFAULT_MODELS_DIR)

    # Decode.
    beam_size: int = 5
    beam_size_partial: int = 1

    # VAD / streaming.
    vad_threshold: float = 0.5
    vad_min_silence_ms: int = 500
    partial_interval_ms: int = 300
    max_segment_sec: float = 30.0

    log_level: str = "INFO"


def load_config() -> STTConfig:
    if SECRETS_PATH.exists():
        load_dotenv(SECRETS_PATH, override=False)
    if not CONFIG_PATH.exists():
        return STTConfig()
    with CONFIG_PATH.open("rb") as f:
        data = tomllib.load(f)
    s = data.get("stt", {})
    return STTConfig(
        listen_host=s.get("listen_host", "127.0.0.1"),
        listen_port=int(s.get("listen_port", 8002)),
        model=s.get("model", "large-v3"),
        language=s.get("language", "en"),
        device=s.get("device", "auto"),
        compute_type=s.get("compute_type", "float16"),
        beam_size=int(s.get("beam_size", 5)),
        beam_size_partial=int(s.get("beam_size_partial", 1)),
        vad_threshold=float(s.get("vad_threshold", 0.5)),
        partial_interval_ms=int(s.get("partial_interval_ms", 300)),
    )
