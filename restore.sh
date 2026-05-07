#!/usr/bin/env bash
# restore.sh — restore from a backup.sh archive. DESTRUCTIVE.
#
# Usage:
#   sudo ./restore.sh --from=path/to/backup.tar.zst
#   sudo ./restore.sh --from=... --target-version=v1.2.3
#   sudo ./restore.sh --from=... --dry-run
#   sudo ./restore.sh --from=... --decrypt-key=/path/to/key
#   sudo ./restore.sh --from=... --yes        skip confirmation
#   sudo ./restore.sh --from=... --skip-checksum

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=installer/lib/common.sh
. "${SCRIPT_DIR}/installer/lib/common.sh"
# shellcheck source=installer/lib/secrets.sh
. "${SCRIPT_DIR}/installer/lib/secrets.sh"
# shellcheck source=installer/lib/migrate.sh
. "${SCRIPT_DIR}/installer/lib/migrate.sh"

RESTORE_LOG="${RESTORE_LOG:-${AIPANEL_LOG_DIR}/restore.log}"

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
FROM=""
TARGET_VERSION=""
DRY_RUN=0
DECRYPT_KEY=""
SAY_YES=0
SKIP_CHECKSUM=0

usage() { sed -n '3,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

for arg in "$@"; do
    case "$arg" in
        --help|-h)             usage ;;
        --from=*)              FROM="${arg#*=}" ;;
        --target-version=*)    TARGET_VERSION="${arg#*=}" ;;
        --dry-run)             DRY_RUN=1 ;;
        --decrypt-key=*)       DECRYPT_KEY="${arg#*=}" ;;
        --yes|-y)              SAY_YES=1 ;;
        --skip-checksum)       SKIP_CHECKSUM=1 ;;
        *) die "Unknown argument: $arg (try --help)" ;;
    esac
done

require_root
init_log_dir

if [[ -z "${AIPANEL_LOGGING_INITIALIZED:-}" ]]; then
    export AIPANEL_LOGGING_INITIALIZED=1
    exec > >(tee -a "${RESTORE_LOG}") 2>&1
fi
trap 'aip_on_error $? "${BASH_COMMAND}" "${BASH_SOURCE[0]}:${LINENO}"' ERR

[[ -n "${FROM}" ]] || die "--from=path/to/backup is required"
[[ -f "${FROM}" ]] || die "Backup not found: ${FROM}"

run_or_dry() { (( DRY_RUN )) && log_info "DRY-RUN: $*" || "$@"; }

# ---------------------------------------------------------------------------
# 1. Verify
# ---------------------------------------------------------------------------
log_step "Verifying ${FROM}"
if (( ! SKIP_CHECKSUM )) && [[ -f "${FROM}.sha256" ]]; then
    log_info "  checking SHA256 against ${FROM}.sha256"
    (cd "$(dirname "${FROM}")" && sha256sum --check "$(basename "${FROM}").sha256")
else
    log_warn "  no .sha256 sibling — skipping integrity check"
fi

# ---------------------------------------------------------------------------
# 2. Stage
# ---------------------------------------------------------------------------
STAGING="$(mktemp -d -t aipanel-restore.XXXXXX)"
trap 'rm -rf "${STAGING}"' EXIT

log_step "Extracting to ${STAGING}"
if [[ "${FROM}" == *.gpg ]]; then
    [[ -n "${DECRYPT_KEY}" ]] || die "Backup is GPG-encrypted; pass --decrypt-key=path/to/key"
    log_info "  decrypting with ${DECRYPT_KEY}"
    gpg --batch --yes --decrypt --recipient-file "${DECRYPT_KEY}" "${FROM}" \
        > "${STAGING}/payload.tar.zst"
    zstd -d -q "${STAGING}/payload.tar.zst" -o "${STAGING}/payload.tar"
    tar -C "${STAGING}" -xf "${STAGING}/payload.tar"
    rm "${STAGING}/payload.tar.zst" "${STAGING}/payload.tar"
else
    zstd -d -q "${FROM}" -c | tar -C "${STAGING}" -xf -
fi

if [[ -f "${STAGING}/MANIFEST.txt" ]]; then
    log_info "  manifest:"
    sed 's/^/    /' "${STAGING}/MANIFEST.txt"
fi

# ---------------------------------------------------------------------------
# 3. Confirm
# ---------------------------------------------------------------------------
if (( ! SAY_YES )) && (( ! DRY_RUN )); then
    log_warn ""
    log_warn "*** This will OVERWRITE the database, Redis snapshot, MinIO buckets,"
    log_warn "*** and /etc/aipanel from the backup. Type RESTORE to proceed."
    printf 'Confirm: '
    read -r reply
    [[ "${reply}" == "RESTORE" ]] || die "Aborted by user."
fi

# ---------------------------------------------------------------------------
# 4. Stop services
# ---------------------------------------------------------------------------
log_step "Stopping aipanel services"
SERVICES=(aipanel-web aipanel-jobs aipanel-workers aipanel-sip
          aipanel-session-mgr aipanel-llm aipanel-stt aipanel-tts)
for svc in "${SERVICES[@]}"; do
    if systemctl list-unit-files --no-legend | awk '{print $1}' | grep -qx "${svc}.service"; then
        run_or_dry systemctl stop "${svc}" || true
    fi
done

# ---------------------------------------------------------------------------
# 5. Postgres
# ---------------------------------------------------------------------------
PG_DUMP="${STAGING}/postgres.dump"
if [[ -f "${PG_DUMP}" ]]; then
    log_step "Restoring PostgreSQL"
    secrets_load
    DB_NAME="${PG_DB_NAME:-aipanel}"
    DB_USER="${PG_DB_USER:-aipanel}"
    log_info "  drop+recreate ${DB_NAME}"
    run_or_dry sudo -u postgres dropdb --if-exists "${DB_NAME}"
    run_or_dry sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}"
    log_info "  pg_restore from ${PG_DUMP}"
    run_or_dry sudo -u postgres pg_restore -d "${DB_NAME}" \
        --no-owner --role="${DB_USER}" "${PG_DUMP}"
else
    log_warn "No postgres.dump in backup; skipping DB restore"
fi

# ---------------------------------------------------------------------------
# 6. Redis
# ---------------------------------------------------------------------------
REDIS_DUMP="${STAGING}/redis.rdb"
if [[ -f "${REDIS_DUMP}" ]]; then
    log_step "Restoring Redis dump"
    run_or_dry systemctl stop redis-server
    run_or_dry install -m 0660 -o redis -g redis "${REDIS_DUMP}" /var/lib/redis/dump.rdb
    run_or_dry systemctl start redis-server
fi

# ---------------------------------------------------------------------------
# 7. MinIO
# ---------------------------------------------------------------------------
MINIO_DIR="${STAGING}/minio"
if [[ -d "${MINIO_DIR}" ]] && command_exists mc; then
    log_step "Restoring MinIO buckets"
    secrets_load
    MC_ALIAS="aipanel-restore-$$"
    run_or_dry mc alias set "${MC_ALIAS}" \
        "http://${MINIO_ENDPOINT:-127.0.0.1:9000}" \
        "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}" --quiet
    for b in "${MINIO_DIR}"/*; do
        [[ -d "${b}" ]] || continue
        bucket="$(basename "${b}")"
        log_info "  mirror back → ${bucket}"
        run_or_dry mc mb --ignore-existing --quiet "${MC_ALIAS}/${bucket}"
        run_or_dry mc mirror --quiet --overwrite "${b}" "${MC_ALIAS}/${bucket}"
    done
    run_or_dry mc alias remove "${MC_ALIAS}" --quiet
fi

# ---------------------------------------------------------------------------
# 8. /etc/aipanel
# ---------------------------------------------------------------------------
CFG_DIR="${STAGING}/etc-aipanel"
if [[ -d "${CFG_DIR}" ]]; then
    log_step "Restoring /etc/aipanel"
    if [[ -d /etc/aipanel ]]; then
        BACKUP_OLD="/etc/aipanel.before-restore-$(date -u +%Y%m%dT%H%M%SZ)"
        log_info "  current /etc/aipanel → ${BACKUP_OLD}"
        run_or_dry mv /etc/aipanel "${BACKUP_OLD}"
    fi
    run_or_dry install -d -m 0750 -o root -g "${AIPANEL_GROUP}" /etc/aipanel
    run_or_dry cp -a "${CFG_DIR}/." /etc/aipanel/
fi

# ---------------------------------------------------------------------------
# 9. Optional: match code version
# ---------------------------------------------------------------------------
if [[ -n "${TARGET_VERSION}" ]]; then
    log_step "Checking out code at ${TARGET_VERSION}"
    if [[ ! -d "${SCRIPT_DIR}/.git" ]]; then
        log_warn "  ${SCRIPT_DIR} is not a git checkout; skipping"
    else
        local_owner="$(stat -c '%U' "${SCRIPT_DIR}")"
        run_or_dry sudo -u "${local_owner}" -H git -C "${SCRIPT_DIR}" fetch --tags
        run_or_dry sudo -u "${local_owner}" -H git -C "${SCRIPT_DIR}" checkout "${TARGET_VERSION}"
    fi
fi

# ---------------------------------------------------------------------------
# 10. Migrations (in case schema advanced since the backup)
# ---------------------------------------------------------------------------
log_step "Schema migrations"
run_or_dry migrate_up

# ---------------------------------------------------------------------------
# 11. Restart
# ---------------------------------------------------------------------------
log_step "Starting services"
for svc in "${SERVICES[@]}"; do
    if systemctl list-unit-files --no-legend | awk '{print $1}' | grep -qx "${svc}.service"; then
        run_or_dry systemctl start "${svc}" || log_warn "  ${svc} failed to start"
    fi
done

# ---------------------------------------------------------------------------
# 12. Health
# ---------------------------------------------------------------------------
log_step "Health check"
ALL_OK=1
for svc in "${SERVICES[@]}"; do
    if systemctl list-unit-files --no-legend | awk '{print $1}' | grep -qx "${svc}.service"; then
        if systemctl is-active --quiet "${svc}"; then
            log_info "  ✓ ${svc}"
        else
            log_error "  ✗ ${svc}"
            ALL_OK=0
        fi
    fi
done

log_info ""
if (( ALL_OK )); then
    log_info "Restore complete."
else
    log_warn "Restore finished but some services are not active. Check journalctl."
fi
