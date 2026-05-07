#!/usr/bin/env bash
# installer/lib/python_env.sh — create the Python 3.11 virtualenv for app code.
#
# The actual application requirements file does not exist yet (lands in a
# later prompt). This module provisions the venv shell and upgrades pip so
# subsequent installs land in a clean environment.

set -euo pipefail

PY_BIN="${PY_BIN:-/usr/bin/python3.11}"
PY_VENV_DIR="${PY_VENV_DIR:-${AIPANEL_PREFIX}/.venv}"

# py_verify_interpreter — make sure python3.11 is callable.
py_verify_interpreter() {
    if [[ ! -x "${PY_BIN}" ]]; then
        die "Python interpreter not found at ${PY_BIN}. Did deps_install_python run?"
    fi
    log_info "Python interpreter: $(${PY_BIN} --version 2>&1)"
}

# py_create_venv — create the venv if missing. Owned by the aipanel user.
py_create_venv() {
    py_verify_interpreter
    if [[ -x "${PY_VENV_DIR}/bin/python" ]]; then
        log_debug "Python venv already exists at ${PY_VENV_DIR}"
    else
        log_info "Creating Python venv at ${PY_VENV_DIR}"
        "${PY_BIN}" -m venv "${PY_VENV_DIR}"
    fi
    chown -R "${AIPANEL_USER}:${AIPANEL_GROUP}" "${PY_VENV_DIR}"
}

# py_upgrade_pip — bring pip / setuptools / wheel current inside the venv.
# Run as the aipanel user so file ownership stays consistent.
py_upgrade_pip() {
    log_info "Upgrading pip / setuptools / wheel inside the venv"
    sudo -u "${AIPANEL_USER}" -H \
        "${PY_VENV_DIR}/bin/python" -m pip install --upgrade --quiet \
        pip setuptools wheel
}

# py_install_requirements — install from requirements.txt if present. The
# file does not exist in v0.1.0; this is a stub that no-ops cleanly.
py_install_requirements() {
    local req="${AIPANEL_PREFIX}/requirements.txt"
    if [[ ! -f "${req}" ]]; then
        log_debug "No requirements.txt yet; skipping pip install"
        return 0
    fi
    log_info "Installing Python requirements from ${req}"
    sudo -u "${AIPANEL_USER}" -H \
        "${PY_VENV_DIR}/bin/python" -m pip install --quiet -r "${req}"
}

# py_setup — module entrypoint.
py_setup() {
    py_create_venv
    py_upgrade_pip
    py_install_requirements
}
