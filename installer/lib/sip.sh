#!/usr/bin/env bash
# installer/lib/sip.sh — bring up the SIP service: venv, deps, PJSIP, systemd.
#
# Idempotent. Requires pjsip.sh and python_env helpers to be sourced.

set -euo pipefail

SIP_PKG_DIR="${SIP_PKG_DIR:-${AIPANEL_PREFIX}/sip}"
SIP_VENV_DIR="${SIP_VENV_DIR:-${SIP_PKG_DIR}/.venv}"
SIP_PY_BIN="${SIP_PY_BIN:-/usr/bin/python3.11}"
SIP_SYSTEMD_UNIT="${SIP_SYSTEMD_UNIT:-aipanel-sip.service}"

# sip_setup_venv — create the venv as the aipanel user; idempotent.
sip_setup_venv() {
    [[ -x "${SIP_PY_BIN}" ]] || die "Python interpreter not found: ${SIP_PY_BIN}"
    if [[ ! -x "${SIP_VENV_DIR}/bin/python" ]]; then
        log_info "Creating SIP venv at ${SIP_VENV_DIR}"
        install -d -m 0755 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" \
            "$(dirname "${SIP_VENV_DIR}")"
        sudo -u "${AIPANEL_USER}" -H "${SIP_PY_BIN}" -m venv "${SIP_VENV_DIR}"
    fi
    sudo -u "${AIPANEL_USER}" -H \
        "${SIP_VENV_DIR}/bin/pip" install --upgrade --quiet \
        pip setuptools wheel
}

# sip_install_pjsip — build/install PJSIP C lib + bindings into our venv.
# pjsip_install runs as root because it touches /usr/local; we re-chown
# the venv afterward so the aipanel user still owns its environment.
sip_install_pjsip() {
    pjsip_install "${SIP_VENV_DIR}"
    chown -R "${AIPANEL_USER}:${AIPANEL_GROUP}" "${SIP_VENV_DIR}"
}

# sip_install_package — pip-install the SIP service package + runtime deps.
sip_install_package() {
    log_info "Installing aipanel_sip package and runtime requirements"
    sudo -u "${AIPANEL_USER}" -H \
        "${SIP_VENV_DIR}/bin/pip" install --quiet -e "${SIP_PKG_DIR}"
}

# sip_install_systemd_unit — copy the unit, daemon-reload, enable (NOT start).
sip_install_systemd_unit() {
    local src="${AIPANEL_PREFIX}/installer/systemd/${SIP_SYSTEMD_UNIT}"
    local dst="/etc/systemd/system/${SIP_SYSTEMD_UNIT}"
    [[ -f "${src}" ]] || die "systemd unit template missing: ${src}"

    log_info "Installing ${dst}"
    install -m 0644 "${src}" "${dst}"
    systemctl daemon-reload
    systemctl enable "${SIP_SYSTEMD_UNIT}"
    log_info "${SIP_SYSTEMD_UNIT} enabled (NOT started — workers required first)"
}

# sip_setup — full module entrypoint.
sip_setup() {
    sip_setup_venv
    sip_install_pjsip
    sip_install_package
    sip_install_systemd_unit
}
