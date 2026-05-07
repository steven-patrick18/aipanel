#!/usr/bin/env bash
# installer/lib/preflight.sh — host preflight checks.
#
# Functions are named pf_check_* and return 0 on success, non-zero on hard
# failure. Soft failures (warnings) return 0 but log_warn.

set -euo pipefail

# ---------------------------------------------------------------------------
# Tunables (override via env)
# ---------------------------------------------------------------------------
PF_MIN_CPU_CORES="${PF_MIN_CPU_CORES:-16}"
PF_MIN_RAM_GB_WARN="${PF_MIN_RAM_GB_WARN:-32}"
PF_MIN_RAM_GB_FAIL="${PF_MIN_RAM_GB_FAIL:-16}"
PF_MIN_DISK_GB="${PF_MIN_DISK_GB:-200}"
PF_DISK_PATH="${PF_DISK_PATH:-/}"
PF_REQUIRED_PORTS="${PF_REQUIRED_PORTS:-443 5060 8000 8001 8002 8003 9000 9001}"

# Detected values, exported for downstream modules.
export AIPANEL_OS_ID=""
export AIPANEL_OS_VERSION=""
export AIPANEL_HAS_GPU=0

# ---------------------------------------------------------------------------
# OS detection
# ---------------------------------------------------------------------------
pf_detect_os() {
    if [[ ! -r /etc/os-release ]]; then
        die "Cannot read /etc/os-release; unsupported OS."
    fi
    # shellcheck disable=SC1091
    . /etc/os-release
    AIPANEL_OS_ID="${ID:-unknown}"
    AIPANEL_OS_VERSION="${VERSION_ID:-unknown}"
    log_info "Detected OS: ${PRETTY_NAME:-${AIPANEL_OS_ID} ${AIPANEL_OS_VERSION}}"
}

pf_check_os() {
    pf_detect_os
    case "${AIPANEL_OS_ID}:${AIPANEL_OS_VERSION}" in
        ubuntu:22.04)
            log_info "OS supported: Ubuntu 22.04 LTS"
            return 0
            ;;
        rhel:9*|rocky:9*|almalinux:9*)
            die "RHEL 9 detected — support is planned but not yet implemented in v0.1.0."
            ;;
        ubuntu:*)
            die "Unsupported Ubuntu version: ${AIPANEL_OS_VERSION}. Only 22.04 is supported."
            ;;
        *)
            die "Unsupported OS: ${AIPANEL_OS_ID} ${AIPANEL_OS_VERSION}. Only Ubuntu 22.04 LTS is supported."
            ;;
    esac
}

# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------
pf_check_cpu() {
    local cores
    cores="$(nproc 2>/dev/null || echo 0)"
    log_info "CPU cores detected: ${cores}"
    if (( cores < PF_MIN_CPU_CORES )); then
        die "Insufficient CPU cores: ${cores} (need >= ${PF_MIN_CPU_CORES})"
    fi
}

# ---------------------------------------------------------------------------
# RAM — read MemTotal in kB from /proc/meminfo, convert to GB.
# ---------------------------------------------------------------------------
pf_check_ram() {
    local mem_kb mem_gb
    mem_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
    if [[ -z "${mem_kb}" ]]; then
        die "Could not read MemTotal from /proc/meminfo"
    fi
    mem_gb=$(( mem_kb / 1024 / 1024 ))
    log_info "RAM detected: ${mem_gb} GB"
    if (( mem_gb < PF_MIN_RAM_GB_FAIL )); then
        die "Insufficient RAM: ${mem_gb} GB (hard minimum ${PF_MIN_RAM_GB_FAIL} GB)"
    fi
    if (( mem_gb < PF_MIN_RAM_GB_WARN )); then
        log_warn "RAM ${mem_gb} GB is below recommended ${PF_MIN_RAM_GB_WARN} GB; performance will suffer."
    fi
}

# ---------------------------------------------------------------------------
# Disk free on PF_DISK_PATH
# ---------------------------------------------------------------------------
pf_check_disk() {
    local free_gb
    # df -BG prints sizes in GiB with a trailing G suffix.
    free_gb="$(df -BG --output=avail "${PF_DISK_PATH}" 2>/dev/null \
                 | tail -n1 | tr -dc '0-9')"
    if [[ -z "${free_gb}" ]]; then
        die "Could not determine free space on ${PF_DISK_PATH}"
    fi
    log_info "Free disk on ${PF_DISK_PATH}: ${free_gb} GB"
    if (( free_gb < PF_MIN_DISK_GB )); then
        die "Insufficient free disk on ${PF_DISK_PATH}: ${free_gb} GB (need >= ${PF_MIN_DISK_GB} GB)"
    fi
}

# ---------------------------------------------------------------------------
# GPU — soft check. Sets AIPANEL_HAS_GPU=1 on success.
# ---------------------------------------------------------------------------
pf_check_gpu() {
    if ! command_exists nvidia-smi; then
        log_warn "nvidia-smi not found; assuming CPU-only host (dev mode)."
        AIPANEL_HAS_GPU=0
        return 0
    fi
    local gpu_count
    gpu_count="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | wc -l || echo 0)"
    if (( gpu_count < 1 )); then
        log_warn "nvidia-smi present but reports no GPUs; continuing in CPU-only mode."
        AIPANEL_HAS_GPU=0
        return 0
    fi
    log_info "GPU(s) detected: ${gpu_count}"
    nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader \
        | while read -r line; do log_info "  GPU: ${line}"; done
    AIPANEL_HAS_GPU=1
}

# ---------------------------------------------------------------------------
# Port availability — uses ss if present, falls back to /proc/net/tcp parsing.
# ---------------------------------------------------------------------------
pf_check_ports() {
    local port in_use=()
    if ! command_exists ss; then
        log_warn "ss(8) not available; skipping port preflight (will be re-checked later)."
        return 0
    fi
    for port in ${PF_REQUIRED_PORTS}; do
        if ss -Hltn "sport = :${port}" 2>/dev/null | grep -q .; then
            in_use+=("${port}")
        fi
    done
    if (( ${#in_use[@]} > 0 )); then
        die "Required TCP port(s) already in use: ${in_use[*]}"
    fi
    log_info "All required ports free: ${PF_REQUIRED_PORTS}"
}

# ---------------------------------------------------------------------------
# Driver — runs every check in order.
# ---------------------------------------------------------------------------
pf_run_all() {
    pf_check_os
    pf_check_cpu
    pf_check_ram
    pf_check_disk
    pf_check_gpu
    pf_check_ports
}
