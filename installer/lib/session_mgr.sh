#!/usr/bin/env bash
# installer/lib/session_mgr.sh — bring up the ViciDial Session Manager.
#
# Adds a venv, installs the package + Playwright + Chromium, and enables
# the systemd unit. Idempotent.

set -euo pipefail

SESSION_MGR_PKG_DIR="${SESSION_MGR_PKG_DIR:-${AIPANEL_PREFIX}/session-mgr}"
SESSION_MGR_VENV_DIR="${SESSION_MGR_VENV_DIR:-${SESSION_MGR_PKG_DIR}/.venv}"
SESSION_MGR_PY_BIN="${SESSION_MGR_PY_BIN:-/usr/bin/python3.11}"
SESSION_MGR_SYSTEMD_UNIT="${SESSION_MGR_SYSTEMD_UNIT:-aipanel-session-mgr.service}"
SESSION_MGR_BROWSERS_DIR="${SESSION_MGR_BROWSERS_DIR:-/var/lib/aipanel/playwright-browsers}"

# Marker so we don't re-run the chromium download on every install run.
SESSION_MGR_BROWSER_MARKER="${SESSION_MGR_BROWSERS_DIR}/.aipanel-installed"

session_mgr_setup_venv() {
    [[ -x "${SESSION_MGR_PY_BIN}" ]] || die "Python not found: ${SESSION_MGR_PY_BIN}"
    if [[ ! -x "${SESSION_MGR_VENV_DIR}/bin/python" ]]; then
        log_info "Creating session-mgr venv at ${SESSION_MGR_VENV_DIR}"
        install -d -m 0755 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" \
            "$(dirname "${SESSION_MGR_VENV_DIR}")"
        sudo -u "${AIPANEL_USER}" -H "${SESSION_MGR_PY_BIN}" -m venv "${SESSION_MGR_VENV_DIR}"
    fi
    sudo -u "${AIPANEL_USER}" -H \
        "${SESSION_MGR_VENV_DIR}/bin/pip" install --upgrade --quiet \
        pip setuptools wheel
}

session_mgr_install_package() {
    log_info "Installing aipanel_vici package"
    sudo -u "${AIPANEL_USER}" -H \
        "${SESSION_MGR_VENV_DIR}/bin/pip" install --quiet -e "${SESSION_MGR_PKG_DIR}"
}

# session_mgr_install_chromium — runs `playwright install chromium`. Skips
# if the marker is already present. Online-only; airgap installs need the
# Chromium tarball staged into ${SESSION_MGR_BROWSERS_DIR} ahead of time
# (documented in README).
session_mgr_install_chromium() {
    if [[ -f "${SESSION_MGR_BROWSER_MARKER}" ]]; then
        log_info "Playwright Chromium already installed at ${SESSION_MGR_BROWSERS_DIR}"
        return 0
    fi

    install -d -m 0755 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" \
        "${SESSION_MGR_BROWSERS_DIR}"

    log_info "Installing Playwright Chromium browser (downloads ~200MB)"
    sudo -u "${AIPANEL_USER}" -H \
        PLAYWRIGHT_BROWSERS_PATH="${SESSION_MGR_BROWSERS_DIR}" \
        "${SESSION_MGR_VENV_DIR}/bin/python" -m playwright install chromium

    # System libs Chromium needs (libnss3, libxkbcommon0, etc). Run as root;
    # idempotent (apt-get install is a no-op when satisfied).
    log_info "Installing Chromium runtime system dependencies"
    if ! "${SESSION_MGR_VENV_DIR}/bin/python" -m playwright install-deps chromium; then
        log_warn "playwright install-deps chromium failed; "
        log_warn "you may need to install: libnss3 libxkbcommon0 libgbm1 libasound2"
    fi

    : > "${SESSION_MGR_BROWSER_MARKER}"
    chown -R "${AIPANEL_USER}:${AIPANEL_GROUP}" "${SESSION_MGR_BROWSERS_DIR}"
}

session_mgr_install_systemd_unit() {
    local src="${AIPANEL_PREFIX}/installer/systemd/${SESSION_MGR_SYSTEMD_UNIT}"
    local dst="/etc/systemd/system/${SESSION_MGR_SYSTEMD_UNIT}"
    [[ -f "${src}" ]] || die "systemd unit template missing: ${src}"
    log_info "Installing ${dst}"
    install -m 0644 "${src}" "${dst}"
    systemctl daemon-reload
    systemctl enable "${SESSION_MGR_SYSTEMD_UNIT}"
    log_info "${SESSION_MGR_SYSTEMD_UNIT} enabled (NOT started)"
}

session_mgr_setup() {
    session_mgr_setup_venv
    session_mgr_install_package
    if [[ "${AIPANEL_MODELS_SOURCE:-online}" != "airgap" ]]; then
        session_mgr_install_chromium
    else
        log_info "Skipping Playwright Chromium install (airgap mode)"
        log_info "Stage Chromium into ${SESSION_MGR_BROWSERS_DIR} manually"
    fi
    session_mgr_install_systemd_unit
}
