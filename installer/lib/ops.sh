#!/usr/bin/env bash
# installer/lib/ops.sh — install operational helpers (aipanelctl + cron).
#
# Idempotent. Symlinks the wrapper into PATH and drops the backup cron file.

set -euo pipefail

OPS_WRAPPER_SRC="${OPS_WRAPPER_SRC:-${AIPANEL_PREFIX}/aipanelctl}"
OPS_WRAPPER_LINK="${OPS_WRAPPER_LINK:-/usr/local/bin/aipanelctl}"
OPS_CRON_SRC="${OPS_CRON_SRC:-${AIPANEL_PREFIX}/installer/cron/aipanel-backup}"
OPS_CRON_DST="${OPS_CRON_DST:-/etc/cron.d/aipanel-backup}"

ops_install_wrapper() {
    [[ -f "${OPS_WRAPPER_SRC}" ]] || die "wrapper missing at ${OPS_WRAPPER_SRC}"
    log_info "Symlinking aipanelctl → ${OPS_WRAPPER_LINK}"
    chmod +x "${OPS_WRAPPER_SRC}" "${AIPANEL_PREFIX}"/{update,backup,restore,status,logs}.sh
    ln -sfn "${OPS_WRAPPER_SRC}" "${OPS_WRAPPER_LINK}"
}

ops_install_cron() {
    [[ -f "${OPS_CRON_SRC}" ]] || die "cron template missing at ${OPS_CRON_SRC}"
    log_info "Installing nightly backup cron at ${OPS_CRON_DST}"
    install -m 0644 "${OPS_CRON_SRC}" "${OPS_CRON_DST}"
}

ops_setup() {
    ops_install_wrapper
    ops_install_cron
}
