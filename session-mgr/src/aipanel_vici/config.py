"""Config loader — reads /etc/aipanel/aipanel.conf [vici] + service-mgr knobs."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

CONFIG_PATH = Path(os.environ.get("AIPANEL_CONF", "/etc/aipanel/aipanel.conf"))
SECRETS_PATH = Path(os.environ.get("AIPANEL_SECRETS", "/etc/aipanel/secrets.env"))


class SessionMgrConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    # API listener.
    listen_host: str = "127.0.0.1"
    listen_port: int = 8010

    # External services.
    db_dsn: str
    redis_url: str

    # Internal API auth (workers send X-AIPanel-Token header).
    auth_token: str

    # ViciDial connection defaults — vicidial_servers row overrides per-deployment.
    vici_default_web_user_admin: str = ""
    vici_default_web_pass_admin: str = ""

    # Tunables.
    supervisor_poll_interval_sec: float = 30.0
    heartbeat_interval_sec: float = 1.5
    heartbeat_max_concurrency: int = 200
    heartbeat_failure_threshold: int = 3

    login_backoff_sec: list[int] = (5, 30, 120, 600)

    # Playwright.
    playwright_browsers_path: str = "/var/lib/aipanel/playwright-browsers"
    browser_pool_size: int = 3
    browser_login_timeout_sec: float = 30.0
    browser_screenshot_dir: str = "/var/log/aipanel/vici-screenshots"

    # ViciDial adapter selection.
    adapter: str = "v2_14"   # only adapter shipped today

    # Ops.
    log_level: str = "INFO"
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 9102


def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(
            f"{name} missing from environment. Was {SECRETS_PATH} loaded?"
        )
    return v


def load_config() -> SessionMgrConfig:
    if SECRETS_PATH.exists():
        load_dotenv(SECRETS_PATH, override=False)
    if not CONFIG_PATH.exists():
        raise RuntimeError(f"Config file not found: {CONFIG_PATH}")
    with CONFIG_PATH.open("rb") as f:
        data = tomllib.load(f)

    db = data["database"]
    redis = data["redis"]
    vici = data.get("vici", {})

    db_pass = _require_env("DB_PASSWORD")
    db_dsn = (
        f"postgresql://{db['user']}:{db_pass}"
        f"@{db['host']}:{db['port']}/{db['name']}"
    )
    redis_pass = os.environ.get("REDIS_PASSWORD") or ""
    redis_auth = f":{redis_pass}@" if redis_pass else ""
    redis_url = f"redis://{redis_auth}{redis['host']}:{redis['port']}/{redis['db']}"

    return SessionMgrConfig(
        listen_host=vici.get("session_mgr_host", "127.0.0.1"),
        listen_port=int(vici.get("session_mgr_port", 8010)),
        db_dsn=db_dsn,
        redis_url=redis_url,
        auth_token=_require_env("SESSION_MGR_TOKEN"),
        adapter=vici.get("adapter", "v2_14"),
        playwright_browsers_path=vici.get(
            "playwright_browsers_path", "/var/lib/aipanel/playwright-browsers"
        ),
        browser_pool_size=int(vici.get("browser_pool_size", 3)),
    )
