#!/usr/bin/env bash
# scripts/bootstrap_admin.sh — create the first tenant + admin user.
#
# Run once after `install.sh`. Subsequent admins/operators/viewers can be
# invited from the panel UI (or via POST /api/v1/tenants/{id}/users).
#
# Usage:
#   sudo ./scripts/bootstrap_admin.sh                   # interactive prompts
#   sudo ./scripts/bootstrap_admin.sh \
#        --tenant="Acme" --email="ops@acme.com" --password='change-me-strong'
#
# Idempotent: re-running with the same email updates the password hash.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=installer/lib/common.sh
. "${SCRIPT_DIR}/installer/lib/common.sh"
# shellcheck source=installer/lib/secrets.sh
. "${SCRIPT_DIR}/installer/lib/secrets.sh"

PANEL_VENV="${PANEL_VENV:-/opt/aipanel/panel/backend/.venv}"
PG_DB_NAME="${PG_DB_NAME:-aipanel}"

TENANT_NAME=""
ADMIN_EMAIL=""
ADMIN_PASSWORD=""

usage() {
    sed -n '3,11p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

for arg in "$@"; do
    case "$arg" in
        --help|-h)         usage ;;
        --tenant=*)        TENANT_NAME="${arg#*=}" ;;
        --email=*)         ADMIN_EMAIL="${arg#*=}" ;;
        --password=*)      ADMIN_PASSWORD="${arg#*=}" ;;
        *) die "Unknown argument: $arg (try --help)" ;;
    esac
done

require_root
secrets_load

[[ -x "${PANEL_VENV}/bin/python" ]] \
    || die "Panel venv missing at ${PANEL_VENV}. Run install.sh first."

# Interactive prompts for whatever wasn't passed on the CLI.
if [[ -z "${TENANT_NAME}" ]]; then
    printf 'Tenant name [Default]: '
    read -r TENANT_NAME
    TENANT_NAME="${TENANT_NAME:-Default}"
fi
if [[ -z "${ADMIN_EMAIL}" ]]; then
    printf 'Admin email: '
    read -r ADMIN_EMAIL
fi
if [[ -z "${ADMIN_PASSWORD}" ]]; then
    printf 'Admin password (≥8 chars, hidden): '
    read -r -s ADMIN_PASSWORD
    printf '\n'
fi

[[ -n "${ADMIN_EMAIL}" ]]                      || die "email is required"
[[ "${ADMIN_EMAIL}" == *@* ]]                  || die "email looks malformed"
(( ${#ADMIN_PASSWORD} >= 8 ))                  || die "password must be ≥ 8 chars"

# ---------------------------------------------------------------------------
# Hash the password via the same passlib argon2 context the login path uses.
# Pipe the password over stdin so it never shows up in `ps`.
# ---------------------------------------------------------------------------
log_info "Hashing password with argon2"
PW_HASH="$(
    printf '%s' "${ADMIN_PASSWORD}" | "${PANEL_VENV}/bin/python" - <<'PY'
import sys
from passlib.context import CryptContext
print(CryptContext(schemes=["argon2"]).hash(sys.stdin.read()))
PY
)"
[[ -n "${PW_HASH}" ]] || die "password hashing failed"

# ---------------------------------------------------------------------------
# Insert via psql with :'var' bindings so SQL escaping is bulletproof.
# Tenant get-or-create by name; user upsert by email (preserves your row if
# you re-run with a new password).
# ---------------------------------------------------------------------------
log_info "Writing tenant + user to ${PG_DB_NAME}"
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${PG_DB_NAME}" \
    -v "tenant_name=${TENANT_NAME}" \
    -v "admin_email=${ADMIN_EMAIL,,}" \
    -v "pw_hash=${PW_HASH}" <<'SQL'
DO $$
DECLARE
    v_tenant_id uuid;
    v_user_id   uuid;
BEGIN
    SELECT id INTO v_tenant_id FROM tenants WHERE name = :'tenant_name' LIMIT 1;
    IF v_tenant_id IS NULL THEN
        INSERT INTO tenants (name) VALUES (:'tenant_name')
        RETURNING id INTO v_tenant_id;
        RAISE NOTICE 'Created tenant % (%)', :'tenant_name', v_tenant_id;
    ELSE
        RAISE NOTICE 'Tenant % already exists (%)', :'tenant_name', v_tenant_id;
    END IF;

    INSERT INTO users (tenant_id, email, password_hash, role)
    VALUES (v_tenant_id, :'admin_email', :'pw_hash', 'admin')
    ON CONFLICT (email) DO UPDATE
        SET password_hash = EXCLUDED.password_hash,
            role          = 'admin'
    RETURNING id INTO v_user_id;

    RAISE NOTICE 'Admin user ready: % (%)', :'admin_email', v_user_id;
END $$;
SQL

log_info ""
log_info "Done."
log_info "  Tenant: ${TENANT_NAME}"
log_info "  Email:  ${ADMIN_EMAIL,,}"
log_info "  Login:  https://$(hostname -f 2>/dev/null || hostname)/login"
