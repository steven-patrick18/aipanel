#!/usr/bin/env bash
# installer/lib/llm.sh — bring up the LLM server (vLLM proxy).

set -euo pipefail

LLM_PKG_DIR="${LLM_PKG_DIR:-${AIPANEL_PREFIX}/llm-server}"
LLM_VENV_DIR="${LLM_VENV_DIR:-${LLM_PKG_DIR}/.venv}"
LLM_PY_BIN="${LLM_PY_BIN:-/usr/bin/python3.11}"
LLM_SYSTEMD_UNIT="${LLM_SYSTEMD_UNIT:-aipanel-llm.service}"

llm_setup_venv() {
    [[ -x "${LLM_PY_BIN}" ]] || die "Python interpreter not found: ${LLM_PY_BIN}"
    if [[ ! -x "${LLM_VENV_DIR}/bin/python" ]]; then
        log_info "Creating LLM venv at ${LLM_VENV_DIR}"
        install -d -m 0755 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" \
            "$(dirname "${LLM_VENV_DIR}")"
        sudo -u "${AIPANEL_USER}" -H "${LLM_PY_BIN}" -m venv "${LLM_VENV_DIR}"
    fi
    sudo -u "${AIPANEL_USER}" -H \
        "${LLM_VENV_DIR}/bin/pip" install --upgrade --quiet pip setuptools wheel
}

llm_install_package() {
    log_info "Installing aipanel_llm package + vLLM"
    sudo -u "${AIPANEL_USER}" -H \
        "${LLM_VENV_DIR}/bin/pip" install --quiet -e "${LLM_PKG_DIR}"
}

llm_install_systemd_unit() {
    local src="${AIPANEL_PREFIX}/installer/systemd/${LLM_SYSTEMD_UNIT}"
    local dst="/etc/systemd/system/${LLM_SYSTEMD_UNIT}"
    [[ -f "${src}" ]] || die "systemd unit template missing: ${src}"
    log_info "Installing ${dst}"
    install -m 0644 "${src}" "${dst}"
    install -m 0755 "${LLM_PKG_DIR}/start.sh" "${LLM_PKG_DIR}/start.sh"
    systemctl daemon-reload
    systemctl enable "${LLM_SYSTEMD_UNIT}"
    log_info "${LLM_SYSTEMD_UNIT} enabled (NOT started)"
}

llm_setup() {
    llm_setup_venv
    llm_install_package
    llm_install_systemd_unit
}
