"""Typed configuration loader for aipanel.

Loads:
    /etc/aipanel/aipanel.conf    (TOML, structural settings)
    /etc/aipanel/secrets.env     (KEY=VALUE, runtime secrets)

Environment override: AIPANEL_CONF / AIPANEL_SECRETS point at alternate paths
(useful for tests). Secrets are merged into ``os.environ`` so the crypto
module and any third-party SDK that reads env vars (boto3 for MinIO, etc.)
sees them transparently.

The ``config`` object is exposed lazily via PEP 562 ``__getattr__`` — callers
write ``from aipanel.config import config`` and the load happens on first
attribute access. Use ``get_config()`` directly when you want explicit control.
"""

from __future__ import annotations

import os
import sys
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

CONFIG_PATH = Path(os.environ.get("AIPANEL_CONF", "/etc/aipanel/aipanel.conf"))
SECRETS_PATH = Path(os.environ.get("AIPANEL_SECRETS", "/etc/aipanel/secrets.env"))


# ---------------------------------------------------------------------------
# Section models
#
# Each model mirrors a [section] in aipanel.conf. Secret-bearing sections
# expose a property that pulls the value from the environment (loaded from
# secrets.env), keeping plain TOML free of sensitive material.
# ---------------------------------------------------------------------------


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DatabaseConfig(_Section):
    host: str
    port: int = 5432
    name: str
    user: str
    pool_min: int = 2
    pool_max: int = 16

    @property
    def password(self) -> str:
        v = os.environ.get("DB_PASSWORD")
        if not v:
            raise RuntimeError("DB_PASSWORD missing (expected from secrets.env)")
        return v

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


class RedisConfig(_Section):
    host: str
    port: int = 6379
    db: int = 0

    @property
    def password(self) -> str | None:
        # Empty / missing = no auth (local-only redis).
        return os.environ.get("REDIS_PASSWORD") or None

    @property
    def url(self) -> str:
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class MinIOConfig(_Section):
    endpoint: str
    console_endpoint: str
    secure: bool = False
    bucket_recordings: str
    bucket_transcripts: str
    bucket_kb: str
    bucket_voices: str

    @property
    def access_key(self) -> str:
        v = os.environ.get("MINIO_ACCESS_KEY")
        if not v:
            raise RuntimeError("MINIO_ACCESS_KEY missing (expected from secrets.env)")
        return v

    @property
    def secret_key(self) -> str:
        v = os.environ.get("MINIO_SECRET_KEY")
        if not v:
            raise RuntimeError("MINIO_SECRET_KEY missing (expected from secrets.env)")
        return v


class SIPConfig(_Section):
    listen_host: str
    listen_port: int = 5060
    public_ip: str
    rtp_port_min: int = 16384
    rtp_port_max: int = 32767
    codec_preference: list[str] = Field(default_factory=lambda: ["opus", "PCMU", "PCMA"])


class LLMConfig(_Section):
    provider: str
    endpoint: str
    model: str
    max_tokens: int = 512
    temperature: float = 0.4
    request_timeout_sec: int = 30


class STTConfig(_Section):
    provider: str
    endpoint: str
    model: str
    language: str = "en"
    vad_threshold: float = 0.5


class TTSConfig(_Section):
    provider: str
    endpoint: str
    default_voice_id: str = ""
    sample_rate: int = 24000


class PanelConfig(_Section):
    listen_host: str
    listen_port: int = 8000
    public_url: str
    session_lifetime_hours: int = 12
    cors_origins: list[str] = Field(default_factory=list)
    access_token_minutes: int = 15
    refresh_token_days: int = 7

    @property
    def jwt_secret(self) -> str:
        v = os.environ.get("JWT_SECRET")
        if not v:
            raise RuntimeError("JWT_SECRET missing (expected from secrets.env)")
        return v


class ClusterConfig(_Section):
    node_role: str
    hostname: str
    heartbeat_interval_sec: int = 10
    quorum_min_nodes: int = 1


# Sections added in later prompts (workers, vici). Optional so existing
# v0.2-era configs still validate.
class WorkerSectionConfig(_Section):
    concurrency: int = 10
    llm_max_response_tokens: int = 256


class ViciSectionConfig(_Section):
    url: str = ""
    enabled: bool = False
    adapter: str = "v2_14"
    session_mgr_host: str = "127.0.0.1"
    session_mgr_port: int = 8010
    playwright_browsers_path: str = "/var/lib/aipanel/playwright-browsers"
    browser_pool_size: int = 3


class EmbedSectionConfig(_Section):
    """Embed-server endpoint config — added in v0.12 for KB ingest + RAG."""
    endpoint: str = "http://127.0.0.1:8004"
    model: str = "BAAI/bge-m3"


class AipanelConfig(BaseModel):
    # extra="ignore" so future TOML additions don't break the loader. The
    # known sections still benefit from extra="forbid" inside _Section.
    model_config = ConfigDict(extra="ignore", frozen=True)

    database: DatabaseConfig
    redis: RedisConfig
    minio: MinIOConfig
    sip: SIPConfig
    llm: LLMConfig
    stt: STTConfig
    tts: TTSConfig
    panel: PanelConfig
    cluster: ClusterConfig
    worker: WorkerSectionConfig = Field(default_factory=WorkerSectionConfig)
    vici: ViciSectionConfig = Field(default_factory=ViciSectionConfig)
    embed: EmbedSectionConfig = Field(default_factory=EmbedSectionConfig)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"Config file not found: {path}")
    with path.open("rb") as f:
        return tomllib.load(f)


@lru_cache(maxsize=1)
def get_config() -> AipanelConfig:
    """Parse aipanel.conf and merge secrets.env into the environment.

    Cached for the process lifetime. Tests that mutate env or files should
    call ``reset_config_cache()`` to force a fresh load.
    """
    if SECRETS_PATH.exists():
        # override=False so an explicit env var (set by systemd EnvironmentFile,
        # for example) wins over the on-disk file.
        load_dotenv(SECRETS_PATH, override=False)
    data = _load_toml(CONFIG_PATH)
    try:
        return AipanelConfig(**data)
    except ValidationError as exc:
        raise RuntimeError(
            f"Invalid configuration in {CONFIG_PATH}:\n{exc}"
        ) from exc


def reset_config_cache() -> None:
    """Clear the cached AipanelConfig; mostly for tests."""
    get_config.cache_clear()


# PEP 562 lazy attribute — `from aipanel.config import config` triggers
# get_config() on first access, not at module import time. This keeps the
# import side-effect-free for tooling that may not have /etc/aipanel set up.
def __getattr__(name: str) -> Any:
    if name == "config":
        return get_config()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Help static analyzers: declare the public surface.
__all__ = [
    "AipanelConfig",
    "DatabaseConfig",
    "RedisConfig",
    "MinIOConfig",
    "SIPConfig",
    "LLMConfig",
    "STTConfig",
    "TTSConfig",
    "PanelConfig",
    "ClusterConfig",
    "get_config",
    "reset_config_cache",
    "config",
]


if __name__ == "__main__":
    # `python -m aipanel.config` prints the resolved config (no secrets).
    cfg = get_config()
    print(cfg.model_dump_json(indent=2), file=sys.stdout)
