#!/usr/bin/env bash
# installer/lib/postgres.sh — install + initialize PostgreSQL 15.
#
# Package install lives in deps_install_postgres (deps.sh). This module
# handles cluster bring-up, role/database creation, and basic config tweaks.
# Schema migrations are owned by installer/lib/migrate.sh; this module
# does NOT apply SQL files itself anymore.
#
# All operations are idempotent.

set -euo pipefail

PG_VERSION="${PG_VERSION:-15}"
PG_CLUSTER="${PG_CLUSTER:-main}"
PG_DB_NAME="${PG_DB_NAME:-aipanel}"
PG_DB_USER="${PG_DB_USER:-aipanel}"
PG_CONF_DIR="/etc/postgresql/${PG_VERSION}/${PG_CLUSTER}"

# pg_install — alias for deps_install_postgres so callers can use module
# vocabulary. Safe to re-invoke.
pg_install() {
    if command_exists psql && [[ -d "${PG_CONF_DIR}" ]]; then
        log_debug "PostgreSQL ${PG_VERSION} already installed"
    else
        deps_install_postgres
    fi
}

# pg_enable_service — ensure the cluster is enabled at boot and running.
pg_enable_service() {
    log_info "Enabling postgresql service"
    systemctl enable --now "postgresql@${PG_VERSION}-${PG_CLUSTER}.service" \
        || systemctl enable --now postgresql.service
}

# pg_create_role_and_db — create the aipanel role/db if missing. Reads the
# password from $DB_PASSWORD (loaded from /etc/aipanel/secrets.env by
# secrets_load). The role is created exactly once; on re-runs the password
# is not changed (changing it would desync from secrets.env, and rotating
# Fernet-encrypted DB rows is out of scope for v0.2).
pg_create_role_and_db() {
    [[ -n "${DB_PASSWORD:-}" ]] || die "pg_create_role_and_db: DB_PASSWORD not in env (call secrets_load first)"

    log_info "Ensuring PostgreSQL role '${PG_DB_USER}' and database '${PG_DB_NAME}' exist"

    local role_exists db_exists
    role_exists="$(sudo -u postgres psql -tAc \
        "SELECT 1 FROM pg_roles WHERE rolname = '${PG_DB_USER}'" 2>/dev/null || true)"
    if [[ "${role_exists}" != "1" ]]; then
        # :'pw' performs psql-side quoting/escaping of the password literal,
        # safe even if the password contains single quotes or backslashes.
        sudo -u postgres psql -v ON_ERROR_STOP=1 \
                              -v "pw=${DB_PASSWORD}" \
            -c "CREATE ROLE ${PG_DB_USER} LOGIN PASSWORD :'pw';"
    else
        log_debug "Role ${PG_DB_USER} already exists; password preserved."
    fi

    db_exists="$(sudo -u postgres psql -tAc \
        "SELECT 1 FROM pg_database WHERE datname = '${PG_DB_NAME}'" 2>/dev/null || true)"
    if [[ "${db_exists}" != "1" ]]; then
        sudo -u postgres psql -v ON_ERROR_STOP=1 -c \
            "CREATE DATABASE ${PG_DB_NAME} OWNER ${PG_DB_USER};"
    else
        log_debug "Database ${PG_DB_NAME} already exists."
    fi
}

# pg_configure — install package, enable service, create role + db. Schema
# migrations are NOT applied here — install.sh calls migrate_up explicitly
# after pg_configure so the two concerns stay independently testable.
pg_configure() {
    pg_install
    pg_enable_service
    pg_create_role_and_db
}
