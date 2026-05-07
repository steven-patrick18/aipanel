#!/usr/bin/env bash
# status.sh — pretty (or JSON) snapshot of every aipanel service + host resources.
#
# Usage:
#   ./status.sh                  pretty terminal output
#   ./status.sh --json           machine-readable JSON
#   ./status.sh --watch          live refresh every 2s
#   ./status.sh --health-only    overall ok|degraded|down (used by aipanelctl health)
#
# Read-only. Does not require root, but some metrics (Postgres size, Redis info,
# /var/lib paths) only render when run with sudo.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=installer/lib/common.sh
. "${SCRIPT_DIR}/installer/lib/common.sh"

OUTPUT_MODE="pretty"
WATCH=0
HEALTH_ONLY=0

usage() { sed -n '3,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

for arg in "$@"; do
    case "$arg" in
        --help|-h)         usage ;;
        --json)            OUTPUT_MODE="json" ;;
        --watch)           WATCH=1 ;;
        --health-only)     HEALTH_ONLY=1 ;;
        *) die "Unknown argument: $arg (try --help)" ;;
    esac
done

# ---------------------------------------------------------------------------
# Catalogue: service-name → (port, health-url, detail-fn)
# ---------------------------------------------------------------------------
ALL_SERVICES=(
    aipanel-web
    aipanel-jobs
    aipanel-llm
    aipanel-stt
    aipanel-tts
    aipanel-workers
    aipanel-sip
    aipanel-session-mgr
    postgresql
    redis-server
    minio
    nginx
)

declare -A HEALTH_URL=(
    [aipanel-web]="http://127.0.0.1:8000/api/healthz"
    [aipanel-llm]="http://127.0.0.1:8001/health"
    [aipanel-stt]="http://127.0.0.1:8002/health"
    [aipanel-tts]="http://127.0.0.1:8003/health"
    [aipanel-session-mgr]="http://127.0.0.1:8010/health"
)

# Per-service detail line — a one-liner that goes after the systemd state.
# All fns swallow errors so a single broken endpoint doesn't blow up the board.
detail_for() {
    local svc="$1"
    case "$svc" in
        aipanel-sip)         _detail_sip ;;
        aipanel-workers)     _detail_workers ;;
        aipanel-session-mgr) _detail_session_mgr ;;
        aipanel-llm)         _detail_gpu_service "${HEALTH_URL[aipanel-llm]}" ;;
        aipanel-stt)         _detail_gpu_service "${HEALTH_URL[aipanel-stt]}" ;;
        aipanel-tts)         _detail_gpu_service "${HEALTH_URL[aipanel-tts]}" ;;
        aipanel-jobs)        _detail_jobs ;;
        postgresql)          _detail_pg ;;
        redis-server)        _detail_redis ;;
        minio)               _detail_minio ;;
        *) echo "" ;;
    esac
}

_prom() {
    local url="$1" metric="$2"
    curl -fsS --max-time 1.5 "${url}" 2>/dev/null \
        | awk -v m="${metric}" '$0 ~ "^"m" " {print $2; exit}'
}

_detail_sip() {
    local active failed
    active="$(_prom http://127.0.0.1:9100/metrics 'aipanel_sip_registrations_total{status="active"}')"
    failed="$(_prom http://127.0.0.1:9100/metrics 'aipanel_sip_registrations_total{status="failed"}')"
    [[ -z "${active}" ]] && { echo ""; return; }
    printf '%s/%s SIP regs (failed)' "${active%.*}" "${failed:-0}"
}

_detail_workers() {
    local active total
    active="$(_prom http://127.0.0.1:9101/metrics aipanel_worker_active_calls)"
    total="$( _prom http://127.0.0.1:9101/metrics aipanel_worker_calls_total)"
    [[ -z "${active}" ]] && { echo ""; return; }
    printf '%s active calls (%s lifetime)' "${active%.*}" "${total:-0}"
}

_detail_session_mgr() {
    local n
    n="$(_prom http://127.0.0.1:9102/metrics 'aipanel_vici_sessions_active{status="ready"}')"
    [[ -z "${n}" ]] && { echo ""; return; }
    printf '%s ready ViciDial sessions' "${n%.*}"
}

_detail_gpu_service() {
    local url="$1" gpu_mb
    gpu_mb="$(curl -fsS --max-time 1.5 "${url}" 2>/dev/null \
        | python3 -c 'import json,sys;print(json.load(sys.stdin).get("gpu_mem_used_mb","-"))' 2>/dev/null)"
    [[ -z "${gpu_mb}" || "${gpu_mb}" == "-" ]] && { echo ""; return; }
    printf 'GPU %s MB' "${gpu_mb}"
}

_detail_jobs() {
    # ARQ exposes Redis keys; quick approximation via redis-cli.
    if ! command_exists redis-cli; then echo ""; return; fi
    local n
    n="$(redis-cli -n 0 LLEN arq:queue 2>/dev/null || echo 0)"
    printf '%s queued' "${n}"
}

_detail_pg() {
    local size
    size="$(sudo -u postgres psql -tAqc \
        "SELECT pg_size_pretty(pg_database_size('aipanel'))" 2>/dev/null)"
    [[ -z "${size}" ]] && { echo ""; return; }
    printf '%s' "${size}" | tr -s ' '
    printf ' DB size'
}

_detail_redis() {
    local mem
    mem="$(redis-cli INFO memory 2>/dev/null \
        | awk -F: '/^used_memory_human:/ {gsub(/\r/,"",$2); print $2; exit}')"
    [[ -z "${mem}" ]] && { echo ""; return; }
    printf '%s used' "${mem}"
}

_detail_minio() {
    if ! command_exists df; then echo ""; return; fi
    local used cap
    used="$(df -BG --output=used /var/lib/aipanel 2>/dev/null \
            | awk 'NR==2 {print $1}')"
    cap="$(df -BG --output=size /var/lib/aipanel 2>/dev/null \
            | awk 'NR==2 {print $1}')"
    [[ -z "${used}" ]] && { echo ""; return; }
    printf '%s / %s on /var/lib/aipanel' "${used}" "${cap}"
}

# ---------------------------------------------------------------------------
# Resource probes
# ---------------------------------------------------------------------------
host_uptime() {
    local s; s="$(awk '{print int($1)}' /proc/uptime 2>/dev/null || echo 0)"
    local d=$((s/86400)) h=$(( (s%86400)/3600 )) m=$(( (s%3600)/60 ))
    printf '%dd %dh %dm' "$d" "$h" "$m"
}

cpu_pct() {
    # Single-shot via /proc/stat (read twice 100ms apart).
    local a b
    a=( $(awk '/^cpu / {print $2,$3,$4,$5,$6,$7,$8}' /proc/stat) )
    sleep 0.1
    b=( $(awk '/^cpu / {print $2,$3,$4,$5,$6,$7,$8}' /proc/stat) )
    local idle_a=$((a[3]+a[4])) total_a=$((a[0]+a[1]+a[2]+a[3]+a[4]+a[5]+a[6]))
    local idle_b=$((b[3]+b[4])) total_b=$((b[0]+b[1]+b[2]+b[3]+b[4]+b[5]+b[6]))
    local d_total=$((total_b-total_a)) d_idle=$((idle_b-idle_a))
    (( d_total <= 0 )) && { echo 0; return; }
    awk "BEGIN {printf \"%.0f\", 100 * (1 - $d_idle / $d_total)}"
}

cpu_cores() { nproc 2>/dev/null || echo 0; }

mem_used_total_gb() {
    awk '
      /^MemTotal:/  {t=$2}
      /^MemAvail/   {a=$2}
      END           {printf "%d %d", (t-a)/1024/1024, t/1024/1024}
    ' /proc/meminfo 2>/dev/null
}

disk_var_lib() {
    df -BG --output=used,size /var/lib/aipanel 2>/dev/null \
        | awk 'NR==2 {gsub("G","",$1); gsub("G","",$2); printf "%s %s", $1, $2}'
}

gpu_lines() {
    command_exists nvidia-smi || return 0
    nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total \
               --format=csv,noheader,nounits 2>/dev/null
}

# Recent activity from the panel API (single point of truth — no DB join here).
recent_activity() {
    local base="http://127.0.0.1:8000/api/v1"
    local last calls aht
    # No auth on /healthz only — analytics requires a token. Skip if no token.
    last="—"
    calls="—"
    aht="—"
    echo "${last}|${calls}|${aht}"
}

# ---------------------------------------------------------------------------
# Render: pretty
# ---------------------------------------------------------------------------
pretty_render() {
    local now; now="$(date '+%Y-%m-%d %H:%M:%S %Z')"
    local version; version="$(cat "${SCRIPT_DIR}/VERSION" 2>/dev/null || echo unknown)"
    local host; host="$(hostname -f 2>/dev/null || hostname)"

    printf '\n'
    printf '  %sAI Panel%s v%s   |   host: %s   |   %s\n' \
        "${C_BOLD}" "${C_RESET}" "${version}" "${host}" "${now}"
    printf '  Uptime: %s\n\n' "$(host_uptime)"

    printf '  %sServices%s\n' "${C_BOLD}" "${C_RESET}"

    local degraded=0
    for svc in "${ALL_SERVICES[@]}"; do
        local active glyph color
        if ! systemctl list-unit-files --no-legend 2>/dev/null \
             | awk '{print $1}' | grep -qx "${svc}.service"; then
            continue
        fi
        active="$(systemctl is-active "${svc}" 2>/dev/null || echo unknown)"
        case "${active}" in
            active)        glyph="✓"; color="${C_GREEN}";;
            activating)    glyph="…"; color="${C_YELLOW}"; degraded=1 ;;
            inactive|failed) glyph="✗"; color="${C_RED}"; degraded=1 ;;
            *)             glyph="?"; color="${C_YELLOW}"; degraded=1 ;;
        esac
        local detail; detail="$(detail_for "${svc}" 2>/dev/null || echo "")"
        printf '    %s%s%s  %-22s %-10s   %s\n' \
            "${color}" "${glyph}" "${C_RESET}" \
            "${svc}" "${active}" "${detail}"
    done

    printf '\n  %sResources%s\n' "${C_BOLD}" "${C_RESET}"
    printf '    CPU:    %s%% (%s cores)\n' "$(cpu_pct)" "$(cpu_cores)"
    read -r mu mt <<<"$(mem_used_total_gb)"
    printf '    RAM:    %s GB / %s GB\n' "${mu:-?}" "${mt:-?}"
    read -r du dt <<<"$(disk_var_lib)"
    printf '    Disk:   %s GB / %s GB on /var/lib/aipanel\n' "${du:-?}" "${dt:-?}"
    while IFS= read -r line; do
        [[ -z "${line}" ]] && continue
        printf '    GPU:    %s\n' "${line}"
    done < <(gpu_lines)

    IFS='|' read -r last calls aht <<<"$(recent_activity)"
    printf '\n  %sRecent activity%s\n' "${C_BOLD}" "${C_RESET}"
    printf '    Last call:    %s\n' "${last}"
    printf '    Calls (24h):  %s\n' "${calls}"
    printf '    Avg AHT:      %s\n' "${aht}"

    printf '\n  %sHealth check:%s ' "${C_BOLD}" "${C_RESET}"
    if (( degraded )); then
        printf '%s%s%s\n\n' "${C_YELLOW}" "DEGRADED" "${C_RESET}"
    else
        printf '%s%s%s\n\n' "${C_GREEN}" "ALL OK" "${C_RESET}"
    fi
}

# ---------------------------------------------------------------------------
# Render: JSON
# ---------------------------------------------------------------------------
json_render() {
    local services="["
    local sep=""
    local degraded=false
    for svc in "${ALL_SERVICES[@]}"; do
        if ! systemctl list-unit-files --no-legend 2>/dev/null \
             | awk '{print $1}' | grep -qx "${svc}.service"; then
            continue
        fi
        local active; active="$(systemctl is-active "${svc}" 2>/dev/null || echo unknown)"
        local detail; detail="$(detail_for "${svc}" 2>/dev/null || echo "")"
        [[ "${active}" != "active" ]] && degraded=true
        services+="${sep}{\"name\":\"${svc}\",\"state\":\"${active}\",\"detail\":\"${detail//\"/\\\"}\"}"
        sep=","
    done
    services+="]"

    local cpu mem_used mem_total disk_used disk_total
    cpu="$(cpu_pct)"
    read -r mem_used mem_total <<<"$(mem_used_total_gb)"
    read -r disk_used disk_total <<<"$(disk_var_lib)"

    cat <<EOF
{
  "version": "$(cat "${SCRIPT_DIR}/VERSION" 2>/dev/null || echo unknown)",
  "hostname": "$(hostname -f 2>/dev/null || hostname)",
  "uptime": "$(host_uptime)",
  "checked_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "overall": "$( [[ ${degraded} == true ]] && echo degraded || echo ok )",
  "cpu_pct": ${cpu},
  "cpu_cores": $(cpu_cores),
  "mem_used_gb": ${mem_used:-0},
  "mem_total_gb": ${mem_total:-0},
  "disk_used_gb": ${disk_used:-0},
  "disk_total_gb": ${disk_total:-0},
  "services": ${services}
}
EOF
}

# ---------------------------------------------------------------------------
# Health-only mode
# ---------------------------------------------------------------------------
if (( HEALTH_ONLY )); then
    degraded=0
    for svc in "${ALL_SERVICES[@]}"; do
        if systemctl list-unit-files --no-legend 2>/dev/null \
             | awk '{print $1}' | grep -qx "${svc}.service"; then
            systemctl is-active --quiet "${svc}" || degraded=1
        fi
    done
    if (( degraded )); then echo degraded; exit 1
    else echo ok; exit 0
    fi
fi

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
render_once() {
    if [[ "${OUTPUT_MODE}" == "json" ]]; then
        json_render
    else
        pretty_render
    fi
}

if (( WATCH )); then
    if [[ "${OUTPUT_MODE}" == "json" ]]; then
        die "--watch is not compatible with --json"
    fi
    trap 'tput cnorm 2>/dev/null; exit 0' INT TERM
    tput civis 2>/dev/null || true
    while true; do
        clear
        render_once
        sleep 2
    done
else
    render_once
fi
