#!/usr/bin/env bash
# llm-server/start.sh — launcher for aipanel-llm.service.
#
# This is intentionally tiny: env setup + exec of the Python wrapper. The
# wrapper spawns vLLM as an internal subprocess and proxies on the configured
# public port so that /health and /metrics can have aipanel-specific shapes.
#
# vLLM CLI args are derived from /etc/aipanel/aipanel.conf [llm] by the
# wrapper (aipanel_llm.launcher.build_vllm_argv), not here — keeping all
# config logic in one place.

set -euo pipefail

# /etc/aipanel/secrets.env exports DB_PASSWORD, REDIS_PASSWORD, etc. Loaded
# by systemd EnvironmentFile too; sourcing again is safe and useful when
# this script is run by hand for debugging.
SECRETS=/etc/aipanel/secrets.env
if [[ -f "${SECRETS}" ]]; then
    set -a
    # shellcheck disable=SC1090
    . "${SECRETS}"
    set +a
fi

# Default to GPU 0 if not pinned by a systemd drop-in or operator override.
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"

# vLLM phones home for usage stats unless this is set.
export VLLM_NO_USAGE_STATS="${VLLM_NO_USAGE_STATS:-1}"
# HF_HUB_OFFLINE forces vLLM to use the pre-downloaded weights and never
# attempt a network fetch — required for airgap installs.
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export HF_HOME="${HF_HOME:-/var/lib/aipanel/models/hf-cache}"

VENV="${VENV:-/opt/aipanel/llm-server/.venv}"
exec "${VENV}/bin/python" -m aipanel_llm.main
