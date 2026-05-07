#!/usr/bin/env bash
# installer/lib/config.sh — render /etc/aipanel/aipanel.conf from template.
#
# Operator edits to aipanel.conf are sacred: this module never overwrites
# an existing file. To pick up template changes the operator must move the
# old file aside.

set -euo pipefail

CONFIG_FILE="${CONFIG_FILE:-${AIPANEL_ETC}/aipanel.conf}"
CONFIG_TEMPLATE="${CONFIG_TEMPLATE:-${AIPANEL_PREFIX}/installer/templates/aipanel.conf.template}"

# config_render — envsubst the template into CONFIG_FILE on first install.
config_render() {
    if [[ -f "${CONFIG_FILE}" ]]; then
        log_info "Config already exists at ${CONFIG_FILE} (preserved)."
        return 0
    fi
    [[ -f "${CONFIG_TEMPLATE}" ]] || die "Config template missing: ${CONFIG_TEMPLATE}"

    log_info "Rendering ${CONFIG_FILE} from template"
    install -d -m 0750 -o root -g "${AIPANEL_GROUP}" "${AIPANEL_ETC}"

    # Defaults for the few env-driven fields. The operator can override by
    # exporting these before running install.sh.
    export PUBLIC_IP="${PUBLIC_IP:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
    export HOSTNAME_FQDN="${HOSTNAME_FQDN:-$(hostname -f 2>/dev/null || hostname)}"
    export PANEL_PUBLIC_URL="${PANEL_PUBLIC_URL:-https://${HOSTNAME_FQDN}}"

    # Restrict envsubst to a known list — otherwise any `$word` token in
    # the template (including TOML values containing $) gets eaten.
    local tmp
    tmp="$(mktemp "${AIPANEL_ETC}/.aipanel.conf.XXXXXX")"
    envsubst '${PUBLIC_IP} ${HOSTNAME_FQDN} ${PANEL_PUBLIC_URL}' \
        < "${CONFIG_TEMPLATE}" > "${tmp}"

    chown "root:${AIPANEL_GROUP}" "${tmp}"
    chmod 0640 "${tmp}"
    mv "${tmp}" "${CONFIG_FILE}"
}
