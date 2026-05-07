"""Spawn + supervise the vLLM OpenAI API server subprocess.

Why a subprocess and not in-process?
- vLLM's openai.api_server module installs its own FastAPI on import + spins
  up its own uvicorn loop. Embedding it in our event loop tangles the two
  shutdown paths and hangs on SIGTERM. Subprocess isolation is simpler and
  matches how vLLM is normally deployed.
- Crash isolation: if vLLM segfaults on a CUDA driver mismatch it doesn't
  take our health/metrics endpoint with it (we still report status=down).
"""

from __future__ import annotations

import asyncio
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import structlog

from .config import LLMConfig

log = structlog.get_logger().bind(component="launcher")


def build_vllm_argv(cfg: LLMConfig) -> list[str]:
    """Compose the CLI for `python -m vllm.entrypoints.openai.api_server`.

    The model path resolves to ``cfg.model_local_path`` if installer/lib/models.sh
    populated it; otherwise we fall back to the HF id and let HF_HUB_OFFLINE
    in start.sh decide whether that fails.
    """
    model_arg = (
        str(cfg.model_local_path)
        if cfg.model_local_path.exists()
        else cfg.model
    )

    argv: list[str] = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--host", cfg.internal_host,
        "--port", str(cfg.internal_port),
        "--model", model_arg,
        "--max-model-len", str(cfg.max_model_len),
        "--gpu-memory-utilization", str(cfg.gpu_memory_utilization),
        "--tensor-parallel-size", str(cfg.tensor_parallel_size),
        "--disable-log-requests",
    ]
    if cfg.enable_auto_tool_choice:
        argv.append("--enable-auto-tool-choice")
        argv += ["--tool-call-parser", cfg.tool_call_parser]
    return argv


class VLLMSubprocess:
    """Owns the vLLM child process for the lifetime of the wrapper."""

    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg
        self._proc: subprocess.Popen | None = None
        self._argv = build_vllm_argv(cfg)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            log.debug("vllm_already_running", pid=self._proc.pid)
            return

        log.info("vllm_starting", argv=self._argv,
                 model=self._argv[self._argv.index("--model") + 1])
        # Inherit stdio so vLLM's logs land in /var/log/aipanel/llm.log via
        # systemd's StandardOutput=append.
        self._proc = subprocess.Popen(
            self._argv,
            stdout=None,
            stderr=None,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
        log.info("vllm_started", pid=self._proc.pid)

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    async def wait_ready(self, http_check, timeout_sec: float = 300.0) -> bool:
        """Poll the internal /health endpoint until 200 OK or timeout.

        ``http_check`` is an async callable: ``async def(url) -> bool``.
        Returns True when ready, False on timeout. We deliberately do NOT
        raise on timeout — caller decides whether to fail-fast or stay up
        in degraded mode.
        """
        deadline = asyncio.get_event_loop().time() + timeout_sec
        url = f"{self.cfg.internal_base_url}/health"
        while asyncio.get_event_loop().time() < deadline:
            if not self.is_alive():
                log.error("vllm_died_during_warmup",
                          returncode=self._proc.returncode if self._proc else None)
                return False
            try:
                if await http_check(url):
                    log.info("vllm_ready", url=url)
                    return True
            except Exception:
                # Connection refused / DNS / etc are expected during boot.
                pass
            await asyncio.sleep(1.0)
        log.warning("vllm_warmup_timeout", url=url, timeout=timeout_sec)
        return False

    def terminate(self, grace_sec: float = 30.0) -> None:
        """SIGTERM, then SIGKILL after grace period. Idempotent."""
        if self._proc is None or self._proc.poll() is not None:
            return
        log.info("vllm_terminating", pid=self._proc.pid, grace_sec=grace_sec)
        try:
            self._proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            self._proc.wait(timeout=grace_sec)
            log.info("vllm_exited_clean", returncode=self._proc.returncode)
        except subprocess.TimeoutExpired:
            log.warning("vllm_force_kill", pid=self._proc.pid)
            self._proc.kill()
            self._proc.wait(timeout=5)


def vllm_executable_present() -> bool:
    """Sanity check at startup so we fail fast with a clear message."""
    return shutil.which(sys.executable) is not None
