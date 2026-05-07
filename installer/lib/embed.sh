#!/usr/bin/env bash
# installer/lib/embed.sh — bring up the embed server (BAAI/bge-m3).

set -euo pipefail

EMBED_PKG_DIR="${EMBED_PKG_DIR:-${AIPANEL_PREFIX}/embed-server}"
EMBED_VENV_DIR="${EMBED_VENV_DIR:-${EMBED_PKG_DIR}/.venv}"
EMBED_PY_BIN="${EMBED_PY_BIN:-/usr/bin/python3.11}"
EMBED_SYSTEMD_UNIT="${EMBED_SYSTEMD_UNIT:-aipanel-embed.service}"
EMBED_MODEL_ID="${EMBED_MODEL_ID:-BAAI/bge-m3}"

embed_setup_venv() {
    [[ -x "${EMBED_PY_BIN}" ]] || die "Python not found: ${EMBED_PY_BIN}"
    if [[ ! -x "${EMBED_VENV_DIR}/bin/python" ]]; then
        log_info "Creating embed venv at ${EMBED_VENV_DIR}"
        install -d -m 0755 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" \
            "$(dirname "${EMBED_VENV_DIR}")"
        sudo -u "${AIPANEL_USER}" -H "${EMBED_PY_BIN}" -m venv "${EMBED_VENV_DIR}"
    fi
    sudo -u "${AIPANEL_USER}" -H \
        "${EMBED_VENV_DIR}/bin/pip" install --upgrade --quiet pip setuptools wheel
}

embed_install_package() {
    log_info "Installing aipanel_embed + sentence-transformers"
    sudo -u "${AIPANEL_USER}" -H \
        "${EMBED_VENV_DIR}/bin/pip" install --quiet -e "${EMBED_PKG_DIR}"
}

embed_download_model() {
    LLM_MODEL_ID="${EMBED_MODEL_ID}" models_download_one embed "${EMBED_MODEL_ID}"
}

embed_install_systemd_unit() {
    local src="${AIPANEL_PREFIX}/installer/systemd/${EMBED_SYSTEMD_UNIT}"
    local dst="/etc/systemd/system/${EMBED_SYSTEMD_UNIT}"
    [[ -f "${src}" ]] || die "systemd unit template missing: ${src}"
    log_info "Installing ${dst}"
    install -m 0644 "${src}" "${dst}"
    systemctl daemon-reload
    systemctl enable "${EMBED_SYSTEMD_UNIT}"
    log_info "${EMBED_SYSTEMD_UNIT} enabled (NOT started)"
}

embed_setup() {
    embed_setup_venv
    embed_install_package
    embed_install_systemd_unit
}
