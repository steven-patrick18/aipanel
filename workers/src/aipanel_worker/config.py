"""Worker config loader — reads /etc/aipanel/aipanel.conf + secrets.env.

The worker pulls from several config sections (database, redis, llm, stt, tts,
minio, vici) plus its own [worker] section for behaviour knobs.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

CONFIG_PATH = Path(os.environ.get("AIPANEL_CONF", "/etc/aipanel/aipanel.conf"))
SECRETS_PATH = Path(os.environ.get("AIPANEL_SECRETS", "/etc/aipanel/secrets.env"))


class WorkerConfig(BaseModel):
    """Resolved config for a worker process."""

    model_config = ConfigDict(frozen=True)

    # Concurrency / queues.
    concurrency: int = 10
    queue_list_key: str = "calls:incoming"
    queue_stream_key: str = "aipanel:worker_requests"
    queue_consumer_group: str = "aipanel-workers"
    reservation_ttl_sec: int = 600

    # External services.
    db_dsn: str
    redis_url: str
    llm_url: str = "http://127.0.0.1:8001"
    stt_url: str = "http://127.0.0.1:8002"
    tts_url: str = "http://127.0.0.1:8003"

    # Vici Session Manager (built in a later prompt — stub-friendly).
    vici_url: str = ""
    vici_enabled: bool = False

    # MinIO for recordings.
    minio_endpoint: str = "127.0.0.1:9000"
    minio_secure: bool = False
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket_recordings: str = "aipanel-recordings"

    # Per-agent defaults — overridden by agent.persona.* in DB.
    response_delay_ms_min: int = 300
    response_delay_ms_max: int = 900
    backchannel_frequency: float = 0.3
    filler_frequency: float = 0.1
    barge_in_min_words: int = 3
    barge_in_min_duration_ms: int = 800
    barge_in_stability_threshold: float = 0.6

    # LLM defaults.
    llm_model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ"
    llm_temperature: float = 0.7
    llm_max_response_tokens: int = 256
    llm_request_timeout_sec: int = 30
    llm_first_token_timeout_sec: int = 10

    # Recording.
    recording_enabled: bool = True
    recording_dir: Path = Field(default=Path("/tmp"))

    # Ops.
    log_level: str = "INFO"
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 9101

    # Graceful shutdown deadline.
    shutdown_drain_sec: float = 30.0


def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(
            f"{name} missing from environment (expected via {SECRETS_PATH})"
        )
    return v


def load_config() -> WorkerConfig:
    if SECRETS_PATH.exists():
        load_dotenv(SECRETS_PATH, override=False)
    if not CONFIG_PATH.exists():
        raise RuntimeError(f"Config file not found: {CONFIG_PATH}")
    with CONFIG_PATH.open("rb") as f:
        data = tomllib.load(f)

    db = data["database"]
    redis = data["redis"]
    llm = data.get("llm", {})
    stt = data.get("stt", {})
    tts = data.get("tts", {})
    minio = data.get("minio", {})
    worker = data.get("worker", {})
    vici = data.get("vici", {})

    db_pass = _require_env("DB_PASSWORD")
    db_dsn = (
        f"postgresql://{db['user']}:{db_pass}"
        f"@{db['host']}:{db['port']}/{db['name']}"
    )
    redis_pass = os.environ.get("REDIS_PASSWORD") or ""
    redis_auth = f":{redis_pass}@" if redis_pass else ""
    redis_url = f"redis://{redis_auth}{redis['host']}:{redis['port']}/{redis['db']}"

    return WorkerConfig(
        concurrency=int(os.environ.get("AIPANEL_WORKER_CONCURRENCY",
                                       worker.get("concurrency", 10))),
        db_dsn=db_dsn,
        redis_url=redis_url,
        llm_url=llm.get("endpoint", "http://127.0.0.1:8001/v1").rstrip("/").rsplit("/v1", 1)[0],
        stt_url=stt.get("endpoint", "http://127.0.0.1:8002"),
        tts_url=tts.get("endpoint", "http://127.0.0.1:8003"),
        vici_url=vici.get("url", ""),
        vici_enabled=bool(vici.get("enabled", False)),
        minio_endpoint=minio.get("endpoint", "127.0.0.1:9000"),
        minio_secure=bool(minio.get("secure", False)),
        minio_access_key=os.environ.get("MINIO_ACCESS_KEY", ""),
        minio_secret_key=os.environ.get("MINIO_SECRET_KEY", ""),
        minio_bucket_recordings=minio.get("bucket_recordings", "aipanel-recordings"),
        llm_model=llm.get("model", "Qwen/Qwen2.5-14B-Instruct-AWQ"),
        llm_temperature=float(llm.get("temperature", 0.7)),
        llm_max_response_tokens=int(worker.get("llm_max_response_tokens", 256)),
        llm_request_timeout_sec=int(llm.get("request_timeout_sec", 30)),
    )
