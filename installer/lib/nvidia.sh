#!/usr/bin/env bash
# installer/lib/nvidia.sh — verify NVIDIA driver + CUDA 12.x toolchain.
#
# We do NOT install drivers from the installer in v0.1.0. Driver install is
# operator territory because it requires kernel headers, secure-boot
# signing, and a reboot. This module only verifies the runtime is healthy
# and reports back. Hard-fails are limited to "GPU was promised but is
# unusable"; absent GPU is a warning (decided in pf_check_gpu).

set -euo pipefail

NVIDIA_MIN_CUDA_MAJOR="${NVIDIA_MIN_CUDA_MAJOR:-12}"

# nvidia_verify_driver — checks that nvidia-smi runs cleanly and reports
# the driver version. Returns 1 if the driver is broken.
nvidia_verify_driver() {
    if ! command_exists nvidia-smi; then
        log_debug "No nvidia-smi; skipping driver verify (CPU-only host)"
        return 0
    fi
    local driver
    driver="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n1)"
    if [[ -z "${driver}" ]]; then
        die "nvidia-smi present but failed to report driver version. Driver may be broken."
    fi
    log_info "NVIDIA driver: ${driver}"
}

# nvidia_verify_cuda — checks for nvcc or, failing that, the CUDA reported
# by nvidia-smi (which is the *runtime* version it can support).
nvidia_verify_cuda() {
    if [[ "${AIPANEL_HAS_GPU:-0}" != "1" ]]; then
        return 0
    fi

    local cuda_major=""
    if command_exists nvcc; then
        # Output format: "Cuda compilation tools, release 12.4, V12.4.131"
        cuda_major="$(nvcc --version 2>/dev/null \
            | awk '/release/ { gsub(/,/, "", $6); split($6, a, "."); print a[1]; exit }')"
        log_info "nvcc reports CUDA major: ${cuda_major:-unknown}"
    else
        # Fall back to the runtime version printed by nvidia-smi.
        cuda_major="$(nvidia-smi 2>/dev/null \
            | awk '/CUDA Version/ { for (i=1;i<=NF;i++) if ($i=="Version:") {split($(i+1), a, "."); print a[1]; exit} }')"
        log_info "nvidia-smi reports CUDA runtime major: ${cuda_major:-unknown}"
        log_warn "nvcc not found; CUDA toolkit may be missing. Install only if you build CUDA code on this host."
    fi

    if [[ -z "${cuda_major}" ]]; then
        log_warn "Could not determine CUDA major version; continuing."
        return 0
    fi
    if (( cuda_major < NVIDIA_MIN_CUDA_MAJOR )); then
        die "CUDA major ${cuda_major} is too old; need >= ${NVIDIA_MIN_CUDA_MAJOR}."
    fi
}

# nvidia_verify_all — module entrypoint.
nvidia_verify_all() {
    nvidia_verify_driver
    nvidia_verify_cuda
}
