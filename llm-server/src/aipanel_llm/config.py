"""Config loader — reads [llm] from /etc/aipanel/aipanel.conf."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

CONFIG_PATH = Path(os.environ.get("AIPANEL_CONF", "/etc/aipanel/aipanel.conf"))
SECRETS_PATH = Path(os.environ.get("AIPANEL_SECRETS", "/etc/aipanel/secrets.env"))

DEFAULT_MODELS_DIR = Path("/var/lib/aipanel/models/llm")


class LLMConfig(BaseModel):
    """Resolved configuration for the LLM proxy + vLLM subprocess."""

    model_config = ConfigDict(frozen=True)

    # Public listener (the wrapper's FastAPI).
    listen_host: str = "127.0.0.1"
    listen_port: int = 8001

    # Internal listener for vLLM subprocess.
    internal_host: str = "127.0.0.1"
    internal_port: int = 8011

    # Model + vLLM knobs.
    model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ"
    max_model_len: int = 8192
    gpu_memory_utilization: float = 0.6
    tensor_parallel_size: int = 1
    enable_auto_tool_choice: bool = True
    tool_call_parser: str = "hermes"

    # Misc.
    log_level: str = "INFO"
    request_timeout_sec: int = 30
    models_dir: Path = Field(default=DEFAULT_MODELS_DIR)

    @property
    def internal_base_url(self) -> str:
        return f"http://{self.internal_host}:{self.internal_port}"

    @property
    def model_local_path(self) -> Path:
        """Where models.sh dropped the weights — preferred over HF lookup."""
        return self.models_dir / self.model.replace("/", "__")


def load_config() -> LLMConfig:
    """Parse aipanel.conf [llm] into an LLMConfig with defaults for missing fields."""
    if SECRETS_PATH.exists():
        load_dotenv(SECRETS_PATH, override=False)
    if not CONFIG_PATH.exists():
        # Fall back to defaults — useful for unit/smoke testing without a
        # full /etc/aipanel layout.
        return LLMConfig()
    with CONFIG_PATH.open("rb") as f:
        data = tomllib.load(f)
    section = data.get("llm", {})
    return LLMConfig(
        listen_host=section.get("listen_host", "127.0.0.1"),
        listen_port=int(section.get("listen_port", 8001)),
        internal_port=int(section.get("internal_port", 8011)),
        model=section.get("model", "Qwen/Qwen2.5-14B-Instruct-AWQ"),
        max_model_len=int(section.get("max_model_len", 8192)),
        gpu_memory_utilization=float(section.get("gpu_memory_utilization", 0.6)),
        tensor_parallel_size=int(section.get("tensor_parallel_size", 1)),
        enable_auto_tool_choice=bool(section.get("enable_auto_tool_choice", True)),
        tool_call_parser=section.get("tool_call_parser", "hermes"),
        request_timeout_sec=int(section.get("request_timeout_sec", 30)),
    )
