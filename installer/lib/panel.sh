#!/usr/bin/env bash
# installer/lib/panel.sh — install the panel backend (web + jobs services).
#
# Idempotent. Builds a single venv shared by both services (smaller install,
# same dependency closure).

set -euo pipefail

PANEL_PKG_DIR="${PANEL_PKG_DIR:-${AIPANEL_PREFIX}/panel/backend}"
PANEL_VENV_DIR="${PANEL_VENV_DIR:-${PANEL_PKG_DIR}/.venv}"
PANEL_PY_BIN="${PANEL_PY_BIN:-/usr/bin/python3.11}"
PANEL_FRONTEND_DIST="${PANEL_FRONTEND_DIST:-${AIPANEL_PREFIX}/panel/frontend/dist}"
PANEL_WEB_UNIT="${PANEL_WEB_UNIT:-aipanel-web.service}"
PANEL_JOBS_UNIT="${PANEL_JOBS_UNIT:-aipanel-jobs.service}"

panel_setup_venv() {
    [[ -x "${PANEL_PY_BIN}" ]] || die "Python not found: ${PANEL_PY_BIN}"
    if [[ ! -x "${PANEL_VENV_DIR}/bin/python" ]]; then
        log_info "Creating panel venv at ${PANEL_VENV_DIR}"
        install -d -m 0755 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" \
            "$(dirname "${PANEL_VENV_DIR}")"
        sudo -u "${AIPANEL_USER}" -H "${PANEL_PY_BIN}" -m venv "${PANEL_VENV_DIR}"
    fi
    sudo -u "${AIPANEL_USER}" -H \
        "${PANEL_VENV_DIR}/bin/pip" install --upgrade --quiet pip setuptools wheel
}

panel_install_package() {
    log_info "Installing aipanel backend + alembic + arq"
    sudo -u "${AIPANEL_USER}" -H \
        "${PANEL_VENV_DIR}/bin/pip" install --quiet -e "${PANEL_PKG_DIR}"
}

panel_alembic_upgrade() {
    log_info "Running alembic upgrade head (stamps the existing schema)"
    # alembic env.py reads ALEMBIC_DATABASE_URL or falls back to the config
    # loader. We supply the asyncpg-aware URL explicitly so alembic uses
    # psycopg2 sync without complaint about driver mismatch.
    local sync_dsn="postgresql://${PG_DB_USER}:${DB_PASSWORD}@127.0.0.1:5432/${PG_DB_NAME}"
    sudo -u "${AIPANEL_USER}" -H \
        ALEMBIC_DATABASE_URL="${sync_dsn}" \
        bash -c "cd '${PANEL_PKG_DIR}' && '${PANEL_VENV_DIR}/bin/alembic' stamp head"
}

panel_setup_frontend_placeholder() {
    install -d -m 0755 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" \
        "${PANEL_FRONTEND_DIST}"
    if [[ ! -f "${PANEL_FRONTEND_DIST}/index.html" ]]; then
        cat > "${PANEL_FRONTEND_DIST}/index.html" <<'HTML'
<!doctype html>
<html><head><meta charset="utf-8"><title>aipanel</title>
<style>body{font-family:system-ui,sans-serif;max-width:42em;margin:4em auto;padding:0 1em;color:#333}
code{background:#f3f3f3;padding:.1em .3em;border-radius:.2em}</style></head>
<body>
<h1>aipanel</h1>
<p>Backend is up. The web dashboard ships in the next release.</p>
<p>API docs (admin token required): <code>/api/docs</code></p>
</body></html>
HTML
        chown "${AIPANEL_USER}:${AIPANEL_GROUP}" "${PANEL_FRONTEND_DIST}/index.html"
    fi
}

panel_install_systemd_units() {
    for unit in "${PANEL_WEB_UNIT}" "${PANEL_JOBS_UNIT}"; do
        local src="${AIPANEL_PREFIX}/installer/systemd/${unit}"
        local dst="/etc/systemd/system/${unit}"
        [[ -f "${src}" ]] || die "systemd unit template missing: ${src}"
        log_info "Installing ${dst}"
        install -m 0644 "${src}" "${dst}"
    done
    systemctl daemon-reload
    systemctl enable "${PANEL_WEB_UNIT}" "${PANEL_JOBS_UNIT}"
    log_info "${PANEL_WEB_UNIT} + ${PANEL_JOBS_UNIT} enabled (NOT started)"
}

panel_setup() {
    panel_setup_venv
    panel_install_package
    panel_alembic_upgrade
    panel_setup_frontend_placeholder
    panel_install_systemd_units
}
