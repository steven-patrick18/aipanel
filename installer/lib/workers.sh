#!/usr/bin/env bash
# installer/lib/workers.sh — bring up the conversation worker process.

set -euo pipefail

WORKERS_PKG_DIR="${WORKERS_PKG_DIR:-${AIPANEL_PREFIX}/workers}"
WORKERS_VENV_DIR="${WORKERS_VENV_DIR:-${WORKERS_PKG_DIR}/.venv}"
WORKERS_PY_BIN="${WORKERS_PY_BIN:-/usr/bin/python3.11}"
WORKERS_SYSTEMD_UNIT="${WORKERS_SYSTEMD_UNIT:-aipanel-workers.service}"

workers_setup_venv() {
    [[ -x "${WORKERS_PY_BIN}" ]] || die "Python interpreter not found: ${WORKERS_PY_BIN}"
    if [[ ! -x "${WORKERS_VENV_DIR}/bin/python" ]]; then
        log_info "Creating workers venv at ${WORKERS_VENV_DIR}"
        install -d -m 0755 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" \
            "$(dirname "${WORKERS_VENV_DIR}")"
        sudo -u "${AIPANEL_USER}" -H "${WORKERS_PY_BIN}" -m venv "${WORKERS_VENV_DIR}"
    fi
    sudo -u "${AIPANEL_USER}" -H \
        "${WORKERS_VENV_DIR}/bin/pip" install --upgrade --quiet pip setuptools wheel
}

workers_install_package() {
    log_info "Installing aipanel_worker package"
    sudo -u "${AIPANEL_USER}" -H \
        "${WORKERS_VENV_DIR}/bin/pip" install --quiet -e "${WORKERS_PKG_DIR}"
}

workers_install_systemd_unit() {
    local src="${AIPANEL_PREFIX}/installer/systemd/${WORKERS_SYSTEMD_UNIT}"
    local dst="/etc/systemd/system/${WORKERS_SYSTEMD_UNIT}"
    [[ -f "${src}" ]] || die "systemd unit template missing: ${src}"
    log_info "Installing ${dst}"
    install -m 0644 "${src}" "${dst}"
    systemctl daemon-reload
    systemctl enable "${WORKERS_SYSTEMD_UNIT}"
    log_info "${WORKERS_SYSTEMD_UNIT} enabled (NOT started)"
}

workers_setup() {
    workers_setup_venv
    workers_install_package
    workers_install_systemd_unit
}
