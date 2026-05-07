"""SIP-service configuration loader.

Reads /etc/aipanel/aipanel.conf and merges /etc/aipanel/secrets.env into the
environment. The SIP service intentionally does NOT depend on the panel
backend's `aipanel` package — it lives in its own venv and just re-parses
the same TOML/.env files.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

CONFIG_PATH = Path(os.environ.get("AIPANEL_CONF", "/etc/aipanel/aipanel.conf"))
SECRETS_PATH = Path(os.environ.get("AIPANEL_SECRETS", "/etc/aipanel/secrets.env"))


class SipConfig(BaseModel):
    """Resolved configuration for the SIP service."""

    model_config = ConfigDict(frozen=True)

    # Postgres (SIP only ever reads, never writes schema).
    db_dsn: str

    # Redis — pubsub + worker request stream.
    redis_url: str

    # SIP listener.
    sip_listen_host: str
    sip_listen_port: int
    sip_public_ip: str
    rtp_port_min: int = 16384
    rtp_port_max: int = 32767

    # Operational paths.
    runtime_dir: str = "/run/aipanel/calls"
    log_level: str = "INFO"

    # Prometheus.
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 9100

    # Encryption — used to decrypt phone_pass_encrypted from the deployments row.
    encryption_key: str

    # Worker dispatch.
    worker_request_stream: str = "aipanel:worker_requests"
    worker_connect_timeout_sec: float = 5.0

    # Account-bring-up tunables.
    register_stagger_sec: float = 60.0
    register_jitter_sec: float = 2.0
    register_backoff_sec: list[int] = Field(default_factory=lambda: [5, 10, 30, 60])

    # Graceful shutdown.
    shutdown_drain_sec: float = 30.0


def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(
            f"{name} missing from environment. Was {SECRETS_PATH} loaded?"
        )
    return v


def load_config() -> SipConfig:
    """Parse aipanel.conf + secrets.env into a SipConfig instance.

    Not cached; the caller (main.py) calls this once at startup.
    """
    if SECRETS_PATH.exists():
        load_dotenv(SECRETS_PATH, override=False)
    if not CONFIG_PATH.exists():
        raise RuntimeError(f"Config file not found: {CONFIG_PATH}")
    with CONFIG_PATH.open("rb") as f:
        data = tomllib.load(f)

    db = data["database"]
    redis = data["redis"]
    sip = data["sip"]

    db_pass = _require_env("DB_PASSWORD")
    db_dsn = (
        f"postgresql://{db['user']}:{db_pass}"
        f"@{db['host']}:{db['port']}/{db['name']}"
    )

    redis_pass = os.environ.get("REDIS_PASSWORD") or ""
    redis_auth = f":{redis_pass}@" if redis_pass else ""
    redis_url = f"redis://{redis_auth}{redis['host']}:{redis['port']}/{redis['db']}"

    return SipConfig(
        db_dsn=db_dsn,
        redis_url=redis_url,
        sip_listen_host=sip["listen_host"],
        sip_listen_port=sip["listen_port"],
        sip_public_ip=sip["public_ip"],
        rtp_port_min=sip.get("rtp_port_min", 16384),
        rtp_port_max=sip.get("rtp_port_max", 32767),
        encryption_key=_require_env("ENCRYPTION_KEY"),
    )
