#!/usr/bin/env bash
# installer/lib/tts.sh — bring up the TTS server (F5-TTS or noop backend).

set -euo pipefail

TTS_PKG_DIR="${TTS_PKG_DIR:-${AIPANEL_PREFIX}/tts-server}"
TTS_VENV_DIR="${TTS_VENV_DIR:-${TTS_PKG_DIR}/.venv}"
TTS_PY_BIN="${TTS_PY_BIN:-/usr/bin/python3.11}"
TTS_SYSTEMD_UNIT="${TTS_SYSTEMD_UNIT:-aipanel-tts.service}"
TTS_VOICES_DIR="${TTS_VOICES_DIR:-/var/lib/aipanel/voices}"

tts_setup_venv() {
    [[ -x "${TTS_PY_BIN}" ]] || die "Python interpreter not found: ${TTS_PY_BIN}"
    if [[ ! -x "${TTS_VENV_DIR}/bin/python" ]]; then
        log_info "Creating TTS venv at ${TTS_VENV_DIR}"
        install -d -m 0755 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" \
            "$(dirname "${TTS_VENV_DIR}")"
        sudo -u "${AIPANEL_USER}" -H "${TTS_PY_BIN}" -m venv "${TTS_VENV_DIR}"
    fi
    sudo -u "${AIPANEL_USER}" -H \
        "${TTS_VENV_DIR}/bin/pip" install --upgrade --quiet pip setuptools wheel
}

tts_install_package() {
    log_info "Installing aipanel_tts package + F5-TTS"
    sudo -u "${AIPANEL_USER}" -H \
        "${TTS_VENV_DIR}/bin/pip" install --quiet -e "${TTS_PKG_DIR}"
}

tts_setup_voice_dir() {
    install -d -m 0750 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" \
        "${TTS_VOICES_DIR}"
}

tts_install_systemd_unit() {
    local src="${AIPANEL_PREFIX}/installer/systemd/${TTS_SYSTEMD_UNIT}"
    local dst="/etc/systemd/system/${TTS_SYSTEMD_UNIT}"
    [[ -f "${src}" ]] || die "systemd unit template missing: ${src}"
    log_info "Installing ${dst}"
    install -m 0644 "${src}" "${dst}"
    systemctl daemon-reload
    systemctl enable "${TTS_SYSTEMD_UNIT}"
    log_info "${TTS_SYSTEMD_UNIT} enabled (NOT started)"
}

tts_setup() {
    tts_setup_venv
    tts_install_package
    tts_setup_voice_dir
    tts_install_systemd_unit
}
