#!/usr/bin/env bash
# installer/lib/nodejs.sh — verify Node 20 and build the frontend if it exists.
#
# Package install lives in deps_install_nodejs (deps.sh). This module covers
# version verification and the frontend build step. The frontend directory
# does not yet exist in v0.1.0; the build is a stub that no-ops cleanly.

set -euo pipefail

NODE_MIN_MAJOR="${NODE_MIN_MAJOR:-20}"
NODE_FRONTEND_DIR="${NODE_FRONTEND_DIR:-${AIPANEL_PREFIX}/frontend}"

# node_verify_version — confirm node is on v20 or newer.
node_verify_version() {
    if ! command_exists node; then
        die "node not found on PATH. Did deps_install_nodejs run?"
    fi
    local v major
    v="$(node --version 2>/dev/null)"   # e.g. "v20.11.1"
    major="${v#v}"
    major="${major%%.*}"
    log_info "Node.js version: ${v}"
    if (( major < NODE_MIN_MAJOR )); then
        die "Node.js ${v} is too old; need >= v${NODE_MIN_MAJOR}.x"
    fi
    if ! command_exists npm; then
        die "npm not found on PATH (it ships with the nodejs package)."
    fi
    log_info "npm version: $(npm --version)"
}

# node_build_frontend — run npm ci + npm run build inside frontend/ if present.
node_build_frontend() {
    if [[ ! -d "${NODE_FRONTEND_DIR}" ]]; then
        log_debug "No frontend directory at ${NODE_FRONTEND_DIR}; skipping build"
        return 0
    fi
    if [[ ! -f "${NODE_FRONTEND_DIR}/package.json" ]]; then
        log_debug "No package.json in ${NODE_FRONTEND_DIR}; skipping build"
        return 0
    fi
    log_info "Building frontend in ${NODE_FRONTEND_DIR}"
    sudo -u "${AIPANEL_USER}" -H bash -c "cd '${NODE_FRONTEND_DIR}' && npm ci && npm run build"
}

# node_setup — module entrypoint.
node_setup() {
    node_verify_version
    node_build_frontend
}
