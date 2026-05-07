"""Config loader — reads [tts] from /etc/aipanel/aipanel.conf."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

CONFIG_PATH = Path(os.environ.get("AIPANEL_CONF", "/etc/aipanel/aipanel.conf"))
SECRETS_PATH = Path(os.environ.get("AIPANEL_SECRETS", "/etc/aipanel/secrets.env"))


class TTSConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    listen_host: str = "127.0.0.1"
    listen_port: int = 8003

    backend: str = "f5"                 # f5 | noop
    device: str = "auto"                # auto | cuda | cpu
    sample_rate: int = 24000            # backend-native sample rate
    output_format_default: str = "ulaw_8000"
    default_voice_id: str = ""

    voices_dir: Path = Path("/var/lib/aipanel/voices")
    models_dir: Path = Path("/var/lib/aipanel/models/tts")

    # Postgres for the voices table.
    db_dsn: str | None = None

    log_level: str = "INFO"


def _build_db_dsn(data: dict) -> str | None:
    db = data.get("database")
    if not db:
        return None
    pw = os.environ.get("DB_PASSWORD")
    if not pw:
        return None
    return (
        f"postgresql://{db['user']}:{pw}"
        f"@{db['host']}:{db['port']}/{db['name']}"
    )


def load_config() -> TTSConfig:
    if SECRETS_PATH.exists():
        load_dotenv(SECRETS_PATH, override=False)
    if not CONFIG_PATH.exists():
        return TTSConfig()
    with CONFIG_PATH.open("rb") as f:
        data = tomllib.load(f)
    t = data.get("tts", {})
    return TTSConfig(
        listen_host=t.get("listen_host", "127.0.0.1"),
        listen_port=int(t.get("listen_port", 8003)),
        backend=t.get("backend", "f5"),
        device=t.get("device", "auto"),
        sample_rate=int(t.get("sample_rate", 24000)),
        output_format_default=t.get("output_format_default", "ulaw_8000"),
        default_voice_id=t.get("default_voice_id", ""),
        voices_dir=Path(t.get("voices_dir", "/var/lib/aipanel/voices")),
        db_dsn=_build_db_dsn(data),
    )
