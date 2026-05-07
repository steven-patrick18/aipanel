#!/usr/bin/env bash
# backup.sh — full-system backup of the aipanel state.
#
# Usage:
#   sudo ./backup.sh                       backup to /var/lib/aipanel/backups
#   sudo ./backup.sh --to=/mnt/nas/backups
#   sudo ./backup.sh --include-recordings  also include MinIO recordings bucket
#   sudo ./backup.sh --encrypt --key-file=/path/to/recipient.asc
#   sudo ./backup.sh --keep=14             retention (default 14)
#   sudo ./backup.sh --quiet               suppress progress lines
#
# Output: aipanel-backup-<host>-<version>-<UTC-ts>.tar.zst (+ .sha256)

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=installer/lib/common.sh
. "${SCRIPT_DIR}/installer/lib/common.sh"
# shellcheck source=installer/lib/secrets.sh
. "${SCRIPT_DIR}/installer/lib/secrets.sh"

BACKUP_LOG="${BACKUP_LOG:-${AIPANEL_LOG_DIR}/backup.log}"
BACKUP_DIR_DEFAULT="/var/lib/aipanel/backups"

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
TO_DIR="${BACKUP_DIR_DEFAULT}"
INCLUDE_RECORDINGS=0
ENCRYPT=0
KEY_FILE=""
KEEP=14
QUIET=0

usage() { sed -n '3,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

for arg in "$@"; do
    case "$arg" in
        --help|-h)              usage ;;
        --to=*)                 TO_DIR="${arg#*=}" ;;
        --include-recordings)   INCLUDE_RECORDINGS=1 ;;
        --encrypt)              ENCRYPT=1 ;;
        --key-file=*)           KEY_FILE="${arg#*=}" ;;
        --keep=*)               KEEP="${arg#*=}" ;;
        --quiet|-q)             QUIET=1 ;;
        *) die "Unknown argument: $arg (try --help)" ;;
    esac
done

require_root
init_log_dir
secrets_load   # need DB_PASSWORD, MINIO creds, ENCRYPTION_KEY

if (( ! QUIET )); then
    if [[ -z "${AIPANEL_LOGGING_INITIALIZED:-}" ]]; then
        export AIPANEL_LOGGING_INITIALIZED=1
        exec > >(tee -a "${BACKUP_LOG}") 2>&1
    fi
fi
trap 'aip_on_error $? "${BASH_COMMAND}" "${BASH_SOURCE[0]}:${LINENO}"' ERR

if (( ENCRYPT )) && [[ -z "${KEY_FILE}" ]]; then
    die "--encrypt requires --key-file=<gpg recipient or passphrase file>"
fi

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HOST="$(hostname -s)"
VERSION="$(cat "${SCRIPT_DIR}/VERSION" 2>/dev/null || echo unknown)"
TS="$(date -u '+%Y%m%dT%H%M%SZ')"
ARCHIVE_NAME="aipanel-backup-${HOST}-${VERSION}-${TS}.tar.zst"
[[ ${ENCRYPT} -eq 1 ]] && ARCHIVE_NAME="${ARCHIVE_NAME}.gpg"
ARCHIVE_PATH="${TO_DIR}/${ARCHIVE_NAME}"
CHECKSUM_PATH="${ARCHIVE_PATH}.sha256"
STAGING="$(mktemp -d -t aipanel-backup.XXXXXX)"
trap 'rm -rf "${STAGING}"' EXIT

install -d -m 0750 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" "${TO_DIR}"

log_info "aipanel backup starting"
log_info "  archive: ${ARCHIVE_PATH}"

# ---------------------------------------------------------------------------
# 1. Postgres
# ---------------------------------------------------------------------------
log_step "PostgreSQL dump (pg_dump -Fc)"
PG_DUMP="${STAGING}/postgres.dump"
sudo -u postgres pg_dump -Fc -Z 9 -d "${PG_DB_NAME:-aipanel}" -f "${PG_DUMP}"
log_info "  → $(stat -c '%s' "${PG_DUMP}" | numfmt --to=iec) bytes"

# ---------------------------------------------------------------------------
# 2. Redis
# ---------------------------------------------------------------------------
log_step "Redis BGSAVE + copy dump.rdb"
REDIS_DUMP="${STAGING}/redis.rdb"
REDIS_RDB="/var/lib/redis/dump.rdb"
if [[ ! -f "${REDIS_RDB}" ]]; then
    log_warn "  ${REDIS_RDB} not found; skipping Redis snapshot"
else
    LAST_BEFORE="$(redis-cli LASTSAVE 2>/dev/null || echo 0)"
    redis-cli BGSAVE >/dev/null 2>&1 || log_warn "  BGSAVE returned non-zero (already in progress?)"
    # Wait up to 60s for the snapshot timestamp to advance.
    deadline=$((SECONDS + 60))
    while (( SECONDS < deadline )); do
        NOW="$(redis-cli LASTSAVE 2>/dev/null || echo 0)"
        [[ "${NOW}" != "${LAST_BEFORE}" ]] && break
        sleep 1
    done
    cp -p "${REDIS_RDB}" "${REDIS_DUMP}"
    log_info "  → $(stat -c '%s' "${REDIS_DUMP}" | numfmt --to=iec) bytes"
fi

# ---------------------------------------------------------------------------
# 3. MinIO
# ---------------------------------------------------------------------------
log_step "MinIO bucket mirror"
MINIO_DIR="${STAGING}/minio"
mkdir -p "${MINIO_DIR}"
if ! command_exists mc; then
    log_warn "  mc (MinIO client) not installed — skipping object storage backup"
    log_warn "  install: 'curl -O https://dl.min.io/client/mc/release/linux-amd64/mc'"
else
    MC_ALIAS="aipanel-backup-$$"
    mc alias set "${MC_ALIAS}" \
        "http://${MINIO_ENDPOINT:-127.0.0.1:9000}" \
        "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}" \
        --quiet >/dev/null 2>&1 || log_warn "  mc alias set failed; bucket sync will be skipped"

    # Always-included buckets (small & necessary):
    for b in aipanel-voices aipanel-kb aipanel-transcripts; do
        log_info "  mirror ${b}"
        mc mirror --quiet --overwrite "${MC_ALIAS}/${b}" "${MINIO_DIR}/${b}" \
            2>/dev/null || log_debug "    bucket ${b} missing/empty"
    done

    if (( INCLUDE_RECORDINGS )); then
        log_info "  mirror aipanel-recordings (large)"
        mc mirror --quiet --overwrite "${MC_ALIAS}/aipanel-recordings" \
            "${MINIO_DIR}/aipanel-recordings" 2>/dev/null \
            || log_debug "    bucket aipanel-recordings missing/empty"
    else
        log_info "  skipping recordings (use --include-recordings to override)"
    fi
    mc alias remove "${MC_ALIAS}" --quiet >/dev/null 2>&1 || true
fi

# ---------------------------------------------------------------------------
# 4. /etc/aipanel
# ---------------------------------------------------------------------------
log_step "Config tarball (/etc/aipanel)"
CFG_DIR="${STAGING}/etc-aipanel"
mkdir -p "${CFG_DIR}"
cp -a /etc/aipanel/. "${CFG_DIR}/" 2>/dev/null || log_warn "  /etc/aipanel missing"

# ---------------------------------------------------------------------------
# 5. Manifest
# ---------------------------------------------------------------------------
log_step "Manifest"
MANIFEST="${STAGING}/MANIFEST.txt"
{
    echo "aipanel backup"
    echo "host:        ${HOST}"
    echo "version:     ${VERSION}"
    echo "git_sha:     $(git -C "${SCRIPT_DIR}" rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "created_at:  ${TS}"
    echo "encrypt:     ${ENCRYPT}"
    echo "include_recordings: ${INCLUDE_RECORDINGS}"
    echo ""
    echo "contents:"
    (cd "${STAGING}" && find . -maxdepth 2 -type f -printf '  %p\t%s\n')
} > "${MANIFEST}"

# Models manifest only (NOT the actual weights — re-downloadable).
if [[ -d /var/lib/aipanel/models ]]; then
    log_step "Models manifest (paths only, not weights)"
    find /var/lib/aipanel/models -mindepth 1 -maxdepth 3 -printf '%p\n' \
        > "${STAGING}/models-manifest.txt" 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# 6. Pack
# ---------------------------------------------------------------------------
log_step "Compress (zstd) → ${ARCHIVE_PATH}"
if ! command_exists zstd; then
    die "zstd is required (apt install zstd)"
fi
if (( ENCRYPT )); then
    if ! command_exists gpg; then
        die "gpg is required for --encrypt (apt install gnupg)"
    fi
    log_info "  → encrypting with key-file ${KEY_FILE}"
    tar -C "${STAGING}" -cf - . \
        | zstd -q --threads=0 -19 -o "${STAGING}/payload.tar.zst"
    gpg --batch --yes --output "${ARCHIVE_PATH}" \
        --encrypt --recipient-file "${KEY_FILE}" \
        "${STAGING}/payload.tar.zst"
else
    tar -C "${STAGING}" -cf - . \
        | zstd -q --threads=0 -19 -o "${ARCHIVE_PATH}"
fi
chown "${AIPANEL_USER}:${AIPANEL_GROUP}" "${ARCHIVE_PATH}"
chmod 0640 "${ARCHIVE_PATH}"

log_step "SHA256"
sha256sum "${ARCHIVE_PATH}" > "${CHECKSUM_PATH}"
chown "${AIPANEL_USER}:${AIPANEL_GROUP}" "${CHECKSUM_PATH}"

# ---------------------------------------------------------------------------
# 7. Retention
# ---------------------------------------------------------------------------
if (( KEEP > 0 )); then
    log_step "Retention (keeping last ${KEEP})"
    # shellcheck disable=SC2012
    ls -1t "${TO_DIR}"/aipanel-backup-*.tar.zst* 2>/dev/null \
        | tail -n +"$((KEEP + 1))" \
        | while read -r f; do
            log_info "  pruning $(basename "${f}")"
            rm -f "${f}" "${f}.sha256"
        done
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
SIZE="$(stat -c '%s' "${ARCHIVE_PATH}" | numfmt --to=iec)"
log_info ""
log_info "Backup complete: ${ARCHIVE_PATH} (${SIZE})"
log_info "Checksum:        ${CHECKSUM_PATH}"
