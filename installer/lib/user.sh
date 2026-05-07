#!/usr/bin/env bash
# installer/lib/user.sh — create the aipanel system user and base directories.

set -euo pipefail

# user_create — idempotent system user + group.
user_create() {
    if getent group "${AIPANEL_GROUP}" >/dev/null; then
        log_debug "Group ${AIPANEL_GROUP} already exists"
    else
        log_info "Creating system group ${AIPANEL_GROUP}"
        groupadd --system "${AIPANEL_GROUP}"
    fi

    if id -u "${AIPANEL_USER}" >/dev/null 2>&1; then
        log_debug "User ${AIPANEL_USER} already exists"
    else
        log_info "Creating system user ${AIPANEL_USER} (home: ${AIPANEL_HOME})"
        useradd --system \
                --gid "${AIPANEL_GROUP}" \
                --home-dir "${AIPANEL_HOME}" \
                --create-home \
                --shell /usr/sbin/nologin \
                "${AIPANEL_USER}"
    fi
}

# user_setup_dirs — base directory layout owned per the spec.
#   /opt/aipanel       root:root    755
#   /etc/aipanel       root:aipanel 750
#   /var/lib/aipanel   aipanel:aipanel 750
#   /var/log/aipanel   aipanel:aipanel 750
user_setup_dirs() {
    ensure_dir "${AIPANEL_PREFIX}" "root:root"                      "0755"
    ensure_dir "${AIPANEL_ETC}"    "root:${AIPANEL_GROUP}"          "0750"
    ensure_dir "${AIPANEL_HOME}"   "${AIPANEL_USER}:${AIPANEL_GROUP}" "0750"
    ensure_dir "${AIPANEL_LOG_DIR}" "${AIPANEL_USER}:${AIPANEL_GROUP}" "0750"
}
