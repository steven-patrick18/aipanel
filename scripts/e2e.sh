#!/usr/bin/env bash
# scripts/e2e.sh — run the in-process pipeline test against fake LLM/STT/TTS/SIP.
#
# Does NOT require Postgres, Redis, real telephony, or any model GPU. Designed
# to run on a CI box in <30s.
#
# Usage:
#   ./scripts/e2e.sh
#   ./scripts/e2e.sh --keepalive   keep the venv around for re-runs

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VENV:-${SCRIPT_DIR}/.venv-e2e}"
PY="${PY:-python3}"

if [[ ! -x "${VENV}/bin/python" ]]; then
    echo "Creating e2e venv at ${VENV}"
    "${PY}" -m venv "${VENV}"
    "${VENV}/bin/pip" install --upgrade --quiet pip wheel
    "${VENV}/bin/pip" install --quiet \
        "fastapi>=0.110" "uvicorn[standard]>=0.27" \
        "httpx>=0.27" "websockets>=12" "pydantic>=2.5" \
        "structlog>=24.1" "redis>=5.0" "psycopg[binary]>=3.1" \
        "pytest>=8.0" "pytest-asyncio>=0.23" \
        "jinja2>=3.1" "numpy>=1.26"
fi

cd "${SCRIPT_DIR}"
PYTHONPATH="${SCRIPT_DIR}/workers/src:${SCRIPT_DIR}/tests" \
    "${VENV}/bin/pytest" tests/e2e -v "$@"
