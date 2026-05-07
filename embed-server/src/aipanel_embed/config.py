"""Embed-server config loader."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

CONFIG_PATH = Path(os.environ.get("AIPANEL_CONF", "/etc/aipanel/aipanel.conf"))
SECRETS_PATH = Path(os.environ.get("AIPANEL_SECRETS", "/etc/aipanel/secrets.env"))


class EmbedConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    listen_host: str = "127.0.0.1"
    listen_port: int = 8004
    model: str = "BAAI/bge-m3"
    device: str = "auto"             # auto | cuda | cpu
    models_dir: Path = Path("/var/lib/aipanel/models/embed")
    log_level: str = "INFO"
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 9103
    max_batch: int = 32              # batched embed for throughput


def load_config() -> EmbedConfig:
    if SECRETS_PATH.exists():
        load_dotenv(SECRETS_PATH, override=False)
    if not CONFIG_PATH.exists():
        return EmbedConfig()
    with CONFIG_PATH.open("rb") as f:
        data = tomllib.load(f)
    e = data.get("embed", {})
    return EmbedConfig(
        listen_host=e.get("listen_host", "127.0.0.1"),
        listen_port=int(e.get("listen_port", 8004)),
        model=e.get("model", "BAAI/bge-m3"),
        device=e.get("device", "auto"),
        max_batch=int(e.get("max_batch", 32)),
    )
