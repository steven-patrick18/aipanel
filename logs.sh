#!/usr/bin/env bash
# logs.sh — tail / search aipanel service logs.
#
# Usage:
#   ./logs.sh                          list available logs
#   ./logs.sh sip                      tail -F /var/log/aipanel/sip.log
#   ./logs.sh sip --grep ERROR         filter as it streams
#   ./logs.sh sip --since "1 hour ago" load via journalctl, exit
#   ./logs.sh sip -n 200               last 200 lines, then follow
#   ./logs.sh all --grep "deployment-xyz"
#                                      tail every aipanel-* log merged
#   ./logs.sh sip --json | jq          structured logs are already JSON

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=installer/lib/common.sh
. "${SCRIPT_DIR}/installer/lib/common.sh"

LOGS_DIR="${LOGS_DIR:-/var/log/aipanel}"

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
TARGET=""
GREP_PAT=""
SINCE=""
TAIL_N=""
JSON=0

usage() { sed -n '3,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

while (( $# > 0 )); do
    case "$1" in
        --help|-h)         usage ;;
        --grep)            GREP_PAT="$2"; shift 2 ;;
        --grep=*)          GREP_PAT="${1#*=}"; shift ;;
        --since)           SINCE="$2"; shift 2 ;;
        --since=*)         SINCE="${1#*=}"; shift ;;
        --json)            JSON=1; shift ;;
        -n)                TAIL_N="$2"; shift 2 ;;
        -n*)               TAIL_N="${1#-n}"; shift ;;
        --) shift; break ;;
        -*) die "Unknown flag: $1" ;;
        *)  if [[ -z "${TARGET}" ]]; then TARGET="$1"; shift
            else die "Multiple targets given; pass one or 'all'."
            fi ;;
    esac
done

# ---------------------------------------------------------------------------
# List mode
# ---------------------------------------------------------------------------
if [[ -z "${TARGET}" ]]; then
    log_info "Available logs in ${LOGS_DIR}:"
    if [[ ! -d "${LOGS_DIR}" ]]; then
        log_warn "  ${LOGS_DIR} does not exist yet."
        exit 0
    fi
    # shellcheck disable=SC2012
    ls -1 "${LOGS_DIR}"/*.log 2>/dev/null \
        | sed 's|^.*/||; s|\.log$||' \
        | awk '{printf "  %-20s\n", $0}'
    log_info ""
    log_info "Usage:  ./logs.sh <name> [--grep PATTERN] [--since '1h ago'] [-n LINES]"
    log_info "        ./logs.sh all       merge-tail all aipanel-* services"
    exit 0
fi

# ---------------------------------------------------------------------------
# Resolve target → file(s) or journalctl unit(s)
# ---------------------------------------------------------------------------
files=()
units=()

if [[ "${TARGET}" == "all" ]]; then
    shopt -s nullglob
    for f in "${LOGS_DIR}"/*.log; do
        files+=("${f}")
    done
    shopt -u nullglob
    if (( ${#files[@]} == 0 )); then
        # Fall back to journalctl for every aipanel-* unit.
        mapfile -t units < <(
            systemctl list-unit-files --no-legend 'aipanel-*.service' 2>/dev/null \
                | awk '{print $1}'
        )
    fi
else
    candidate="${LOGS_DIR}/${TARGET}.log"
    if [[ -f "${candidate}" ]]; then
        files+=("${candidate}")
    elif systemctl list-unit-files --no-legend "${TARGET}.service" 2>/dev/null \
         | grep -q .; then
        units+=("${TARGET}.service")
    elif systemctl list-unit-files --no-legend "aipanel-${TARGET}.service" 2>/dev/null \
         | grep -q .; then
        units+=("aipanel-${TARGET}.service")
    else
        die "No log file ${candidate} and no matching systemd unit."
    fi
fi

# ---------------------------------------------------------------------------
# Mode 1: --since → journalctl one-shot (don't tail)
# ---------------------------------------------------------------------------
if [[ -n "${SINCE}" ]]; then
    if (( ${#units[@]} == 0 )); then
        # Map files → units when possible (assume <name> matches <name>.service
        # or aipanel-<name>.service).
        for f in "${files[@]}"; do
            local_name="$(basename "${f}" .log)"
            for cand in "${local_name}" "aipanel-${local_name}"; do
                if systemctl list-unit-files --no-legend "${cand}.service" 2>/dev/null \
                     | grep -q .; then
                    units+=("${cand}.service")
                    break
                fi
            done
        done
    fi
    args=(--since "${SINCE}")
    [[ -n "${TAIL_N}" ]] && args+=(-n "${TAIL_N}")
    (( JSON )) && args+=(-o cat) || args+=(-o cat)
    for u in "${units[@]}"; do args+=(-u "${u}"); done
    if (( ${#units[@]} == 0 )); then
        log_warn "No journald units resolved; falling back to file tail."
    else
        if [[ -n "${GREP_PAT}" ]]; then
            journalctl "${args[@]}" | grep --color=auto -E "${GREP_PAT}" || true
        else
            journalctl "${args[@]}"
        fi
        exit 0
    fi
fi

# ---------------------------------------------------------------------------
# Mode 2: live tail of the file(s)
# ---------------------------------------------------------------------------
if (( ${#files[@]} > 0 )); then
    tail_args=(-F)
    [[ -n "${TAIL_N}" ]] && tail_args=(-n "${TAIL_N}" -F)
    if [[ -n "${GREP_PAT}" ]]; then
        tail "${tail_args[@]}" "${files[@]}" | grep --line-buffered --color=auto -E "${GREP_PAT}"
    else
        tail "${tail_args[@]}" "${files[@]}"
    fi
    exit 0
fi

# ---------------------------------------------------------------------------
# Mode 3: live journalctl follow
# ---------------------------------------------------------------------------
if (( ${#units[@]} > 0 )); then
    args=()
    [[ -n "${TAIL_N}" ]] && args+=(-n "${TAIL_N}")
    args+=(-f -o cat)
    for u in "${units[@]}"; do args+=(-u "${u}"); done
    if [[ -n "${GREP_PAT}" ]]; then
        journalctl "${args[@]}" | grep --line-buffered --color=auto -E "${GREP_PAT}"
    else
        journalctl "${args[@]}"
    fi
fi
