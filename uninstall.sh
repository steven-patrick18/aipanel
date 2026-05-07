#!/usr/bin/env bash
# uninstall.sh — stop services, remove the aipanel user and data.
#
# This is destructive. We prompt for explicit confirmation and require
# the operator to type the word REMOVE.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=installer/lib/common.sh
. "${SCRIPT_DIR}/installer/lib/common.sh"

require_root
init_log_dir

trap 'aip_on_error $? "${BASH_COMMAND}" "${BASH_SOURCE[0]}:${LINENO}"' ERR

log_warn "This will remove the aipanel user, /var/lib/aipanel, /etc/aipanel,"
log_warn "/var/log/aipanel, and stop/disable any aipanel-* systemd services."
log_warn "Postgres / Redis / MinIO data managed by aipanel will be deleted."
log_warn "OS packages installed for aipanel are NOT removed."

if [[ "${AIPANEL_FORCE:-0}" != "1" ]]; then
    printf 'Type REMOVE to confirm: '
    read -r answer
    if [[ "${answer}" != "REMOVE" ]]; then
        die "Aborted; nothing was changed."
    fi
fi

log_step "Stop and disable aipanel-* services"
# List units matching our naming convention. The grep cannot find anything
# in v0.1.0 — that's fine, this is hardened for future versions.
mapfile -t units < <(
    systemctl list-unit-files --no-legend 'aipanel-*.service' 2>/dev/null \
        | awk '{print $1}'
)
for unit in "${units[@]:-}"; do
    [[ -z "${unit}" ]] && continue
    log_info "Stopping ${unit}"
    systemctl stop "${unit}" 2>/dev/null || true
    systemctl disable "${unit}" 2>/dev/null || true
done

log_step "Remove aipanel data and config directories"
for d in "${AIPANEL_HOME}" "${AIPANEL_LOG_DIR}" "${AIPANEL_ETC}"; do
    if [[ -d "${d}" ]]; then
        log_info "Deleting ${d}"
        rm -rf -- "${d}"
    fi
done

log_step "Remove aipanel system user and group"
if id -u "${AIPANEL_USER}" >/dev/null 2>&1; then
    log_info "Deleting user ${AIPANEL_USER}"
    userdel "${AIPANEL_USER}" 2>/dev/null || true
fi
if getent group "${AIPANEL_GROUP}" >/dev/null; then
    log_info "Deleting group ${AIPANEL_GROUP}"
    groupdel "${AIPANEL_GROUP}" 2>/dev/null || true
fi

log_info ""
log_info "Uninstall complete. /opt/aipanel left in place — remove manually if desired."
