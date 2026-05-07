#!/usr/bin/env bash
# installer/lib/redis.sh — configure Redis for aipanel use.
#
# The redis-server package install happens in deps_install_base. This module
# applies our overrides and ensures the service is running.

set -euo pipefail

REDIS_CONF="${REDIS_CONF:-/etc/redis/redis.conf}"
REDIS_OVERRIDE_DIR="${REDIS_OVERRIDE_DIR:-/etc/redis/aipanel.conf.d}"
REDIS_OVERRIDE_FILE="${REDIS_OVERRIDE_DIR}/00-aipanel.conf"

# redis_install — verifies the package landed; defers to deps if not.
redis_install() {
    if command_exists redis-server; then
        log_debug "redis-server already installed"
        return 0
    fi
    DEBIAN_FRONTEND=noninteractive apt-get install -y redis-server
}

# redis_configure — write our override snippet and reload the service.
# We bind to localhost only and disable RDB snapshots in favor of AOF for
# the queue/state workload aipanel will use.
redis_configure() {
    redis_install
    log_info "Writing Redis override config to ${REDIS_OVERRIDE_FILE}"
    install -d -m 0755 "${REDIS_OVERRIDE_DIR}"
    cat > "${REDIS_OVERRIDE_FILE}" <<'EOF'
# Managed by aipanel installer. Do not edit by hand; changes will be
# overwritten on the next install run.

bind 127.0.0.1 -::1
protected-mode yes
port 6379
tcp-backlog 511
timeout 0
tcp-keepalive 300

# Persistence: AOF for durability, snapshots disabled.
save ""
appendonly yes
appendfsync everysec

# Memory policy — let the app set this once we know the deployment shape.
# A safe default for the installer skeleton:
maxmemory-policy allkeys-lru
EOF

    # Include the override from the main config exactly once.
    if ! grep -q "include ${REDIS_OVERRIDE_FILE}" "${REDIS_CONF}" 2>/dev/null; then
        log_info "Hooking override into ${REDIS_CONF}"
        printf '\n# aipanel override\ninclude %s\n' "${REDIS_OVERRIDE_FILE}" \
            >> "${REDIS_CONF}"
    fi

    log_info "Enabling and restarting redis-server"
    systemctl enable redis-server.service
    systemctl restart redis-server.service
}
