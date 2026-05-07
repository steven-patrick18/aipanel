#!/usr/bin/env bash
# installer/lib/nginx.sh — render the aipanel nginx site + ensure SSL cert.

set -euo pipefail

NGINX_CONF_TEMPLATE="${NGINX_CONF_TEMPLATE:-${AIPANEL_PREFIX}/installer/nginx/aipanel.conf.template}"
NGINX_SITE_AVAILABLE="${NGINX_SITE_AVAILABLE:-/etc/nginx/sites-available/aipanel.conf}"
NGINX_SITE_ENABLED="${NGINX_SITE_ENABLED:-/etc/nginx/sites-enabled/aipanel.conf}"
NGINX_SSL_DIR="${NGINX_SSL_DIR:-/etc/aipanel/ssl}"
NGINX_SERVER_NAME="${NGINX_SERVER_NAME:-_}"
PANEL_FRONTEND_DIST="${PANEL_FRONTEND_DIST:-${AIPANEL_PREFIX}/panel/frontend/dist}"

nginx_ensure_ssl_cert() {
    install -d -m 0750 -o root -g "${AIPANEL_GROUP}" "${NGINX_SSL_DIR}"
    local cert="${NGINX_SSL_DIR}/cert.pem"
    local key="${NGINX_SSL_DIR}/key.pem"
    if [[ -f "${cert}" ]] && [[ -f "${key}" ]]; then
        log_info "TLS cert already present at ${cert}"
        return 0
    fi
    log_warn "Generating self-signed TLS cert for ${NGINX_SERVER_NAME}"
    log_warn "Replace ${cert} / ${key} with a real cert in production."
    openssl req -x509 -nodes -days 730 -newkey rsa:2048 \
        -keyout "${key}" -out "${cert}" \
        -subj "/CN=${NGINX_SERVER_NAME}" \
        -addext "subjectAltName=DNS:${NGINX_SERVER_NAME},IP:127.0.0.1" \
        2>/dev/null
    chmod 0640 "${key}" "${cert}"
    chown "root:${AIPANEL_GROUP}" "${key}" "${cert}"
}

nginx_render_site() {
    [[ -f "${NGINX_CONF_TEMPLATE}" ]] || die "nginx template missing: ${NGINX_CONF_TEMPLATE}"
    log_info "Rendering ${NGINX_SITE_AVAILABLE}"
    export NGINX_SERVER_NAME PANEL_FRONTEND_DIST NGINX_SSL_DIR
    envsubst '${NGINX_SERVER_NAME} ${PANEL_FRONTEND_DIST} ${NGINX_SSL_DIR}' \
        < "${NGINX_CONF_TEMPLATE}" > "${NGINX_SITE_AVAILABLE}"
    if [[ ! -L "${NGINX_SITE_ENABLED}" ]]; then
        ln -sf "${NGINX_SITE_AVAILABLE}" "${NGINX_SITE_ENABLED}"
    fi
    # Disable the stock default site if Debian / Ubuntu installed it.
    if [[ -L /etc/nginx/sites-enabled/default ]]; then
        rm -f /etc/nginx/sites-enabled/default
    fi
}

nginx_reload() {
    if nginx -t 2>/dev/null; then
        systemctl reload nginx 2>/dev/null \
            || systemctl restart nginx 2>/dev/null \
            || log_warn "nginx reload failed; check manually"
    else
        log_warn "nginx -t reported errors; not reloading"
    fi
}

nginx_setup() {
    nginx_ensure_ssl_cert
    nginx_render_site
    nginx_reload
}
