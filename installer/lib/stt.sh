#!/usr/bin/env bash
# installer/lib/stt.sh — bring up the STT server (faster-whisper + silero-vad).

set -euo pipefail

STT_PKG_DIR="${STT_PKG_DIR:-${AIPANEL_PREFIX}/stt-server}"
STT_VENV_DIR="${STT_VENV_DIR:-${STT_PKG_DIR}/.venv}"
STT_PY_BIN="${STT_PY_BIN:-/usr/bin/python3.11}"
STT_SYSTEMD_UNIT="${STT_SYSTEMD_UNIT:-aipanel-stt.service}"

stt_setup_venv() {
    [[ -x "${STT_PY_BIN}" ]] || die "Python interpreter not found: ${STT_PY_BIN}"
    if [[ ! -x "${STT_VENV_DIR}/bin/python" ]]; then
        log_info "Creating STT venv at ${STT_VENV_DIR}"
        install -d -m 0755 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" \
            "$(dirname "${STT_VENV_DIR}")"
        sudo -u "${AIPANEL_USER}" -H "${STT_PY_BIN}" -m venv "${STT_VENV_DIR}"
    fi
    sudo -u "${AIPANEL_USER}" -H \
        "${STT_VENV_DIR}/bin/pip" install --upgrade --quiet pip setuptools wheel
}

stt_install_package() {
    log_info "Installing aipanel_stt package + faster-whisper + silero-vad"
    sudo -u "${AIPANEL_USER}" -H \
        "${STT_VENV_DIR}/bin/pip" install --quiet -e "${STT_PKG_DIR}"
}

stt_install_systemd_unit() {
    local src="${AIPANEL_PREFIX}/installer/systemd/${STT_SYSTEMD_UNIT}"
    local dst="/etc/systemd/system/${STT_SYSTEMD_UNIT}"
    [[ -f "${src}" ]] || die "systemd unit template missing: ${src}"
    log_info "Installing ${dst}"
    install -m 0644 "${src}" "${dst}"
    systemctl daemon-reload
    systemctl enable "${STT_SYSTEMD_UNIT}"
    log_info "${STT_SYSTEMD_UNIT} enabled (NOT started)"
}

stt_setup() {
    stt_setup_venv
    stt_install_package
    stt_install_systemd_unit
}
