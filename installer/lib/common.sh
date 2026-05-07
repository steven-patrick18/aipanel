#!/usr/bin/env bash
# installer/lib/common.sh — logging, color output, error handling.
#
# Sourced by install.sh and other top-level scripts. Do NOT execute directly.

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths / globals
# ---------------------------------------------------------------------------
AIPANEL_LOG_DIR="${AIPANEL_LOG_DIR:-/var/log/aipanel}"
AIPANEL_LOG_FILE="${AIPANEL_LOG_FILE:-${AIPANEL_LOG_DIR}/install.log}"
AIPANEL_LOCK_FILE="${AIPANEL_LOCK_FILE:-/var/run/aipanel-install.lock}"
AIPANEL_USER="${AIPANEL_USER:-aipanel}"
AIPANEL_GROUP="${AIPANEL_GROUP:-aipanel}"
AIPANEL_HOME="${AIPANEL_HOME:-/var/lib/aipanel}"
AIPANEL_ETC="${AIPANEL_ETC:-/etc/aipanel}"
AIPANEL_PREFIX="${AIPANEL_PREFIX:-/opt/aipanel}"

# Step counter used by log_step.
AIPANEL_STEP_NUM="${AIPANEL_STEP_NUM:-0}"

# ---------------------------------------------------------------------------
# Color handling — auto-disable if stdout is not a TTY or NO_COLOR is set.
# ---------------------------------------------------------------------------
if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
    C_RESET=$'\033[0m'
    C_BOLD=$'\033[1m'
    C_RED=$'\033[31m'
    C_GREEN=$'\033[32m'
    C_YELLOW=$'\033[33m'
    C_BLUE=$'\033[34m'
    C_CYAN=$'\033[36m'
else
    C_RESET=""
    C_BOLD=""
    C_RED=""
    C_GREEN=""
    C_YELLOW=""
    C_BLUE=""
    C_CYAN=""
fi

# ---------------------------------------------------------------------------
# Logging primitives. Every line is timestamped and tee'd to the log file
# by the parent install.sh — these helpers just write to stdout/stderr.
# ---------------------------------------------------------------------------
_aip_ts() { date '+%Y-%m-%d %H:%M:%S'; }

log_info() {
    printf '%s %s[INFO]%s  %s\n' "$(_aip_ts)" "${C_GREEN}" "${C_RESET}" "$*"
}

log_warn() {
    printf '%s %s[WARN]%s  %s\n' "$(_aip_ts)" "${C_YELLOW}" "${C_RESET}" "$*" >&2
}

log_error() {
    printf '%s %s[ERROR]%s %s\n' "$(_aip_ts)" "${C_RED}" "${C_RESET}" "$*" >&2
}

log_debug() {
    [[ "${AIPANEL_DEBUG:-0}" = "1" ]] || return 0
    printf '%s %s[DEBUG]%s %s\n' "$(_aip_ts)" "${C_CYAN}" "${C_RESET}" "$*"
}

log_step() {
    AIPANEL_STEP_NUM=$((AIPANEL_STEP_NUM + 1))
    printf '\n%s==> Step %d:%s %s%s%s\n' \
        "${C_BOLD}${C_BLUE}" "${AIPANEL_STEP_NUM}" "${C_RESET}" \
        "${C_BOLD}" "$*" "${C_RESET}"
}

# ---------------------------------------------------------------------------
# Error trap — prints step, command, file:line, and exit code on any
# uncaught failure. Install with: trap 'aip_on_error $? "$BASH_COMMAND" \
#   "${BASH_SOURCE[0]}:${LINENO}"' ERR
# ---------------------------------------------------------------------------
aip_on_error() {
    local exit_code="${1:-?}"
    local cmd="${2:-?}"
    local where="${3:-?}"
    log_error "Installation failed."
    log_error "  Step:     ${AIPANEL_STEP_NUM}"
    log_error "  Command:  ${cmd}"
    log_error "  Location: ${where}"
    log_error "  Exit:     ${exit_code}"
    log_error "Full log:   ${AIPANEL_LOG_FILE}"
    exit "${exit_code}"
}

# Convenience: fail with a clear message, no stack noise.
die() {
    log_error "$*"
    exit 1
}

# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

# require_root — exit non-zero if not running as root.
require_root() {
    if [[ "$(id -u)" -ne 0 ]]; then
        die "This script must be run as root (try: sudo $0)"
    fi
}

# command_exists <name> — true if the command is on PATH.
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# ensure_dir <path> <owner> <mode>
ensure_dir() {
    local path="$1" owner="$2" mode="$3"
    if [[ ! -d "${path}" ]]; then
        mkdir -p "${path}"
        log_debug "Created ${path}"
    fi
    chown "${owner}" "${path}"
    chmod "${mode}" "${path}"
}

# acquire_install_lock — flock on AIPANEL_LOCK_FILE; exits if held.
acquire_install_lock() {
    # File descriptor 200 is conventional for flock-on-fd patterns.
    exec 200>"${AIPANEL_LOCK_FILE}"
    if ! flock -n 200; then
        die "Another aipanel install is in progress (lock: ${AIPANEL_LOCK_FILE})"
    fi
    log_debug "Acquired install lock on ${AIPANEL_LOCK_FILE}"
}

# init_log_dir — create log dir before tee can write to it. Owned by root
# until the aipanel user exists; install.sh re-chowns later.
init_log_dir() {
    if [[ ! -d "${AIPANEL_LOG_DIR}" ]]; then
        mkdir -p "${AIPANEL_LOG_DIR}"
        chmod 0750 "${AIPANEL_LOG_DIR}"
    fi
}
