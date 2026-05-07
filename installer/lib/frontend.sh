#!/usr/bin/env bash
# installer/lib/frontend.sh — build the React SPA and drop it into nginx's docroot.
#
# Idempotent. Always runs `npm ci && npm run build`; the placeholder index.html
# from panel.sh gets overwritten by the real Vite build output.

set -euo pipefail

FRONTEND_SRC_DIR="${FRONTEND_SRC_DIR:-${AIPANEL_PREFIX}/panel/frontend}"
FRONTEND_DIST_DIR="${FRONTEND_DIST_DIR:-${FRONTEND_SRC_DIR}/dist}"
FRONTEND_NPM_BIN="${FRONTEND_NPM_BIN:-/usr/bin/npm}"

frontend_check_npm() {
    if [[ ! -x "${FRONTEND_NPM_BIN}" ]] && ! command -v npm >/dev/null 2>&1; then
        die "npm not found. deps_install_nodejs should have provided Node 20."
    fi
}

frontend_install_deps() {
    log_info "Installing frontend npm dependencies (this can take a minute)"
    sudo -u "${AIPANEL_USER}" -H bash -c \
        "cd '${FRONTEND_SRC_DIR}' && npm ci --no-audit --no-fund --prefer-offline"
}

frontend_build() {
    log_info "Building frontend (vite)"
    sudo -u "${AIPANEL_USER}" -H bash -c \
        "cd '${FRONTEND_SRC_DIR}' && npm run build"
    if [[ ! -f "${FRONTEND_DIST_DIR}/index.html" ]]; then
        die "Vite build did not produce ${FRONTEND_DIST_DIR}/index.html"
    fi
    log_info "Frontend built into ${FRONTEND_DIST_DIR}"
}

# frontend_setup — full module entrypoint. Skipped automatically when the
# frontend directory has no package.json (e.g. someone unpacked just the
# backend tarball).
frontend_setup() {
    if [[ ! -f "${FRONTEND_SRC_DIR}/package.json" ]]; then
        log_warn "No package.json at ${FRONTEND_SRC_DIR}; skipping frontend build"
        return 0
    fi
    install -d -m 0755 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" \
        "${FRONTEND_SRC_DIR}"
    chown -R "${AIPANEL_USER}:${AIPANEL_GROUP}" "${FRONTEND_SRC_DIR}"
    frontend_check_npm
    frontend_install_deps
    frontend_build
}
