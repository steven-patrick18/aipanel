#!/usr/bin/env bash
# update.sh — upgrade aipanel to a new version with auto-rollback on failure.
#
# Safe to re-run. Holds a flock so two updates can't race. Logs to
# /var/log/aipanel/update.log via tee.
#
# Usage:
#   sudo ./update.sh                     update to latest tag on current branch
#   sudo ./update.sh --to=v1.2.3         update to a specific tag/SHA
#   sudo ./update.sh --rollback          revert to the previously-installed version
#   sudo ./update.sh --dry-run           print what would change, no side effects
#   sudo ./update.sh --skip-backup       skip pre-update backup (NOT recommended)
#   sudo ./update.sh --offline --bundle=path.tar.gz
#                                        apply an airgap bundle instead of git fetch
#   sudo ./update.sh --yes               skip confirmation prompt
#   sudo ./update.sh --force             force re-install even if version unchanged
#   sudo ./update.sh --force-with-active-calls
#                                        proceed even if calls are in progress
#   sudo ./update.sh --keep=N            backups to retain (default 10)

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=installer/lib/common.sh
. "${SCRIPT_DIR}/installer/lib/common.sh"

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
UPDATE_LOCK_FILE="${UPDATE_LOCK_FILE:-/var/run/aipanel-update.lock}"
UPDATE_LOG_FILE="${UPDATE_LOG_FILE:-${AIPANEL_LOG_DIR}/update.log}"
UPDATE_BACKUP_DIR="${UPDATE_BACKUP_DIR:-/var/lib/aipanel/backups}"
UPDATE_PREV_VERSION_FILE="${UPDATE_PREV_VERSION_FILE:-/var/lib/aipanel/.previous-version}"
UPDATE_BACKUP_KEEP_DEFAULT=10

# Service groups, ordered for restart (start in this order, stop in reverse).
SERVICES_INFRA=(postgresql redis-server minio nginx)
SERVICES_MODELS=(aipanel-llm aipanel-stt aipanel-tts)
SERVICES_APP=(aipanel-session-mgr aipanel-workers aipanel-sip aipanel-jobs aipanel-web)

declare -A SERVICE_HEALTH_URL=(
    [aipanel-web]="http://127.0.0.1:8000/api/healthz"
    [aipanel-llm]="http://127.0.0.1:8001/health"
    [aipanel-stt]="http://127.0.0.1:8002/health"
    [aipanel-tts]="http://127.0.0.1:8003/health"
    [aipanel-session-mgr]="http://127.0.0.1:8010/health"
)

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
TARGET=""
DO_ROLLBACK=0
DRY_RUN=0
SKIP_BACKUP=0
OFFLINE=0
BUNDLE_PATH=""
SAY_YES=0
FORCE=0
FORCE_WITH_CALLS=0
KEEP=$UPDATE_BACKUP_KEEP_DEFAULT

usage() {
    sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

for arg in "$@"; do
    case "$arg" in
        --help|-h)               usage ;;
        --to=*)                  TARGET="${arg#*=}" ;;
        --rollback)              DO_ROLLBACK=1 ;;
        --dry-run)               DRY_RUN=1 ;;
        --skip-backup)           SKIP_BACKUP=1 ;;
        --offline)               OFFLINE=1 ;;
        --bundle=*)              BUNDLE_PATH="${arg#*=}" ;;
        --yes|-y)                SAY_YES=1 ;;
        --force)                 FORCE=1 ;;
        --force-with-active-calls) FORCE_WITH_CALLS=1 ;;
        --keep=*)                KEEP="${arg#*=}" ;;
        *) die "Unknown argument: $arg (try --help)" ;;
    esac
done

require_root
init_log_dir

if [[ -z "${AIPANEL_LOGGING_INITIALIZED:-}" ]]; then
    export AIPANEL_LOGGING_INITIALIZED=1
    exec > >(tee -a "${UPDATE_LOG_FILE}") 2>&1
fi

trap 'aip_on_error $? "${BASH_COMMAND}" "${BASH_SOURCE[0]}:${LINENO}"' ERR

# Use a separate lock file from install.sh so an in-flight install doesn't
# block manual update kicks (and vice versa).
acquire_lock_at() {
    local file="$1"
    exec 201>"${file}"
    if ! flock -n 201; then
        die "Another update appears to be in progress (lock: ${file})"
    fi
}
acquire_lock_at "${UPDATE_LOCK_FILE}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

git_owner() {
    stat -c '%U' "${SCRIPT_DIR}"
}

run_git() {
    sudo -u "$(git_owner)" -H git -C "${SCRIPT_DIR}" "$@"
}

current_version() {
    cat "${SCRIPT_DIR}/VERSION" 2>/dev/null || echo "unknown"
}

current_sha() {
    run_git rev-parse HEAD 2>/dev/null || echo "unknown"
}

resolve_target_ref() {
    if [[ -n "${TARGET}" ]]; then
        echo "${TARGET}"
        return
    fi
    # Default: latest annotated tag.
    run_git fetch --tags --quiet 2>/dev/null || true
    local latest
    latest="$(run_git tag --sort=-v:refname | head -n1)"
    if [[ -z "${latest}" ]]; then
        die "No tags in repository; pass --to=<ref> explicitly."
    fi
    echo "${latest}"
}

count_active_calls() {
    # Cheap probe via the worker metrics endpoint; absent → assume 0.
    local v
    v="$(curl -fsS --max-time 2 http://127.0.0.1:9101/metrics 2>/dev/null \
         | awk '/^aipanel_worker_active_calls / {print $2}' | head -n1)"
    [[ -n "${v}" ]] || echo 0
    [[ -n "${v}" ]] && echo "${v%.*}"
}

run_or_dry() {
    if (( DRY_RUN )); then
        log_info "DRY-RUN: $*"
    else
        "$@"
    fi
}

http_health_ok() {
    local url="$1"
    curl -fsS --max-time 5 "${url}" >/dev/null 2>&1
}

# Wait up to N seconds for a service's /health endpoint to return 200 (or
# for systemctl to report active if no health URL is registered).
wait_service_healthy() {
    local svc="$1" deadline=$((SECONDS + 90))
    while (( SECONDS < deadline )); do
        if ! systemctl is-active --quiet "${svc}"; then
            sleep 2
            continue
        fi
        local url="${SERVICE_HEALTH_URL[$svc]:-}"
        if [[ -z "${url}" ]] || http_health_ok "${url}"; then
            return 0
        fi
        sleep 2
    done
    return 1
}

# changed_paths <from-sha> <to-sha> — newline list. May fail if either
# ref is not present locally; caller should handle.
changed_paths() {
    run_git diff --name-only "$1...$2" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

if [[ ! -d "${SCRIPT_DIR}/.git" ]]; then
    die "${SCRIPT_DIR} is not a git checkout. Replace the tree manually, then re-run install.sh."
fi

if (( DO_ROLLBACK )); then
    log_step "Rollback requested"
    if [[ ! -s "${UPDATE_PREV_VERSION_FILE}" ]]; then
        die "No previous version recorded at ${UPDATE_PREV_VERSION_FILE}; cannot rollback."
    fi
    TARGET="$(cat "${UPDATE_PREV_VERSION_FILE}")"
    log_info "Rolling back to ${TARGET}"
fi

CURRENT_VERSION="$(current_version)"
CURRENT_SHA="$(current_sha)"
TARGET_REF="$(resolve_target_ref)"

# Resolve target → SHA (without checking out).
TARGET_SHA="$(run_git rev-parse "${TARGET_REF}^{commit}" 2>/dev/null || echo "")"
if [[ -z "${TARGET_SHA}" ]]; then
    # Maybe it's a remote ref we don't have yet; fetch and retry.
    run_git fetch --all --tags --prune --quiet
    TARGET_SHA="$(run_git rev-parse "${TARGET_REF}^{commit}" 2>/dev/null || echo "")"
fi
[[ -n "${TARGET_SHA}" ]] || die "Could not resolve ${TARGET_REF} to a commit. Available tags: $(run_git tag | tr '\n' ' ')"

if [[ "${TARGET_SHA}" == "${CURRENT_SHA}" ]] && (( ! FORCE )); then
    log_info "Already at ${TARGET_REF} (${TARGET_SHA:0:8}). Use --force to re-run anyway."
    exit 0
fi

log_step "Update plan"
log_info "  Current: ${CURRENT_VERSION} (${CURRENT_SHA:0:12})"
log_info "  Target:  ${TARGET_REF} (${TARGET_SHA:0:12})"
log_info ""
log_info "Commits being applied:"
run_git log --oneline "${CURRENT_SHA}..${TARGET_SHA}" 2>/dev/null \
    | head -n 30 | sed 's/^/    /' || true

# ---------------------------------------------------------------------------
# Active-call check
# ---------------------------------------------------------------------------
ACTIVE_CALLS="$(count_active_calls)"
if (( ACTIVE_CALLS > 0 )) && (( ! FORCE_WITH_CALLS )); then
    die "${ACTIVE_CALLS} call(s) in progress. Re-run with --force-with-active-calls to drop them."
fi

# ---------------------------------------------------------------------------
# Confirmation
# ---------------------------------------------------------------------------
if (( ! SAY_YES )) && (( ! DRY_RUN )); then
    printf '\nApply this update? [y/N] '
    read -r reply
    [[ "${reply,,}" == "y" || "${reply,,}" == "yes" ]] \
        || die "Aborted by user."
fi

# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------
BACKUP_TAG="$(date '+%Y%m%dT%H%M%SZ')-${CURRENT_VERSION}"
BACKUP_SQL="${UPDATE_BACKUP_DIR}/pre-update-${BACKUP_TAG}.sql.gz"
BACKUP_CONFIG="${UPDATE_BACKUP_DIR}/pre-update-${BACKUP_TAG}-config.tar.gz"

if (( SKIP_BACKUP )); then
    log_warn "Skipping pre-update backup (--skip-backup)"
else
    log_step "Pre-update backup"
    run_or_dry install -d -m 0750 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" \
        "${UPDATE_BACKUP_DIR}"
    log_info "  pg_dump → ${BACKUP_SQL}"
    if (( ! DRY_RUN )); then
        sudo -u postgres pg_dump -Fc -Z 9 -d "${PG_DB_NAME:-aipanel}" \
            > "${BACKUP_SQL}"
        chown "${AIPANEL_USER}:${AIPANEL_GROUP}" "${BACKUP_SQL}"
    fi
    log_info "  /etc/aipanel → ${BACKUP_CONFIG}"
    run_or_dry tar -czf "${BACKUP_CONFIG}" -C / etc/aipanel
    if (( ! DRY_RUN )); then
        chown "${AIPANEL_USER}:${AIPANEL_GROUP}" "${BACKUP_CONFIG}"
    fi
fi

# Record the previous SHA before checking out new code so rollback works.
if (( ! DRY_RUN )); then
    install -d -m 0750 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" \
        "$(dirname "${UPDATE_PREV_VERSION_FILE}")"
    echo "${CURRENT_SHA}" > "${UPDATE_PREV_VERSION_FILE}"
fi

# ---------------------------------------------------------------------------
# Pull / extract code
# ---------------------------------------------------------------------------
log_step "Fetch code"

if (( OFFLINE )); then
    [[ -f "${BUNDLE_PATH}" ]] || die "--offline requires --bundle=path/to/airgap.tar.gz"
    log_info "Applying offline bundle ${BUNDLE_PATH}"
    run_or_dry tar -xzf "${BUNDLE_PATH}" -C "${SCRIPT_DIR}" --strip-components=1
else
    run_or_dry run_git fetch --all --tags --prune
    log_info "Checking out ${TARGET_REF} (${TARGET_SHA:0:12})"
    run_or_dry run_git checkout --detach "${TARGET_SHA}"
    run_or_dry run_git submodule update --init --recursive 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# Detect what changed → decide which install steps to re-run
# ---------------------------------------------------------------------------
log_step "Detect changes"

CHANGED="$(changed_paths "${CURRENT_SHA}" "${TARGET_SHA}")"
log_debug "Changed files:"
echo "${CHANGED}" | sed 's/^/    /' | head -n 30

paths_match() {
    local pattern="$1"
    grep -qE "${pattern}" <<<"${CHANGED}"
}

NEED_DEPS=0;     paths_match '^installer/lib/deps\.sh$|^installer/lib/pjsip\.sh$' && NEED_DEPS=1
NEED_PANEL=0;    paths_match '^panel/backend/' && NEED_PANEL=1
NEED_SIP=0;      paths_match '^sip/' && NEED_SIP=1
NEED_LLM=0;      paths_match '^llm-server/' && NEED_LLM=1
NEED_STT=0;      paths_match '^stt-server/' && NEED_STT=1
NEED_TTS=0;      paths_match '^tts-server/' && NEED_TTS=1
NEED_WORKERS=0;  paths_match '^workers/' && NEED_WORKERS=1
NEED_SESSION=0;  paths_match '^session-mgr/' && NEED_SESSION=1
NEED_FRONTEND=0; paths_match '^panel/frontend/' && NEED_FRONTEND=1
NEED_NGINX=0;    paths_match '^installer/nginx/' && NEED_NGINX=1
NEED_SYSTEMD=0;  paths_match '^installer/systemd/' && NEED_SYSTEMD=1
NEED_MIGRATE=0;  paths_match '^installer/migrations/|^panel/backend/alembic/' && NEED_MIGRATE=1

# ---------------------------------------------------------------------------
# Apply changes (rollback on any failure once we start touching the system)
# ---------------------------------------------------------------------------

cleanup_rollback() {
    local exit_code=$?
    set +e
    log_error "Update failed at exit ${exit_code} — initiating rollback"

    # Restore code first; subsequent service restarts will use old binaries.
    log_warn "Rolling back code to ${CURRENT_SHA:0:12}"
    run_git checkout --detach "${CURRENT_SHA}" || true

    if (( ! SKIP_BACKUP )) && [[ -s "${BACKUP_SQL}" ]]; then
        log_warn "Restoring DB from ${BACKUP_SQL}"
        sudo -u postgres dropdb --if-exists "${PG_DB_NAME:-aipanel}" || true
        sudo -u postgres createdb -O "${PG_DB_USER:-aipanel}" "${PG_DB_NAME:-aipanel}" || true
        gunzip -c "${BACKUP_SQL}" | sudo -u postgres pg_restore \
            -d "${PG_DB_NAME:-aipanel}" --clean --if-exists || true
    else
        log_warn "No DB backup available; rollback restored code only."
    fi

    log_warn "Restarting services on rolled-back code"
    for svc in "${SERVICES_APP[@]}" "${SERVICES_MODELS[@]}"; do
        systemctl restart "${svc}" >/dev/null 2>&1 || true
    done

    log_error "Rollback complete. System should be back at ${CURRENT_VERSION}."
    log_error "Investigate ${UPDATE_LOG_FILE} for the failure cause."
    exit "${exit_code}"
}
if (( ! DRY_RUN )); then
    trap cleanup_rollback ERR
fi

# Source the lib helpers that handle each step. These are idempotent — safe
# to call even when nothing in their domain changed; we gate on NEED_* to
# avoid unnecessary work.
LIB_DIR="${SCRIPT_DIR}/installer/lib"
# shellcheck source=installer/lib/secrets.sh
. "${LIB_DIR}/secrets.sh"
# shellcheck source=installer/lib/postgres.sh
. "${LIB_DIR}/postgres.sh"
# shellcheck source=installer/lib/migrate.sh
. "${LIB_DIR}/migrate.sh"
secrets_load   # need DB_PASSWORD for migrate + restore paths

(( NEED_DEPS )) && {
    log_step "OS packages changed → re-running deps"
    # shellcheck source=installer/lib/deps.sh
    . "${LIB_DIR}/deps.sh"
    run_or_dry deps_install_all
}

# Re-pip per-service if its sources changed. Each lib has its own setup.
maybe_setup() {
    local lib="$1" entry="$2"
    # shellcheck disable=SC1090
    . "${LIB_DIR}/${lib}"
    run_or_dry "${entry}"
}

(( NEED_PANEL ))   && { log_step "Panel backend changed";  maybe_setup panel.sh   panel_setup; }
(( NEED_SIP ))     && { log_step "SIP service changed";    maybe_setup sip.sh     sip_setup; }
(( NEED_LLM ))     && { log_step "LLM server changed";     maybe_setup llm.sh     llm_setup; }
(( NEED_STT ))     && { log_step "STT server changed";     maybe_setup stt.sh     stt_setup; }
(( NEED_TTS ))     && { log_step "TTS server changed";     maybe_setup tts.sh     tts_setup; }
(( NEED_WORKERS )) && { log_step "Workers changed";        maybe_setup workers.sh workers_setup; }
(( NEED_SESSION )) && { log_step "Session-mgr changed";    maybe_setup session_mgr.sh session_mgr_setup; }
(( NEED_FRONTEND )) && { log_step "Frontend changed";      maybe_setup frontend.sh frontend_setup; }
(( NEED_NGINX ))    && { log_step "Nginx config changed";  maybe_setup nginx.sh   nginx_setup; }

(( NEED_SYSTEMD )) && {
    log_step "Systemd units changed → daemon-reload"
    run_or_dry systemctl daemon-reload
}

(( NEED_MIGRATE )) && {
    log_step "Schema migrations present → applying"
    run_or_dry migrate_up
}

# ---------------------------------------------------------------------------
# Restart services in dependency order
# ---------------------------------------------------------------------------
log_step "Rolling restart"

restart_one() {
    local svc="$1"
    if ! systemctl list-unit-files --no-legend | awk '{print $1}' | grep -qx "${svc}.service"; then
        log_debug "Skipping ${svc} (not installed)"
        return 0
    fi
    log_info "  restart ${svc}"
    run_or_dry systemctl restart "${svc}"
    if (( ! DRY_RUN )); then
        if ! wait_service_healthy "${svc}"; then
            log_error "Service ${svc} did not come back healthy"
            return 1
        fi
    fi
}

# Models: rolling (one at a time) so we don't blow the GPU.
for svc in "${SERVICES_MODELS[@]}"; do
    restart_one "${svc}"
done

# App services in order.
for svc in "${SERVICES_APP[@]}"; do
    restart_one "${svc}"
done

# Reload nginx (don't restart — keeps connections).
if (( NEED_NGINX )); then
    log_info "  reload nginx"
    run_or_dry systemctl reload nginx
fi

# ---------------------------------------------------------------------------
# Final health check
# ---------------------------------------------------------------------------
log_step "Post-update health"

ALL_OK=1
for svc in "${SERVICES_APP[@]}" "${SERVICES_MODELS[@]}"; do
    if systemctl list-unit-files --no-legend | awk '{print $1}' | grep -qx "${svc}.service"; then
        if systemctl is-active --quiet "${svc}"; then
            log_info "  ✓ ${svc} active"
        else
            log_error "  ✗ ${svc} not active"
            ALL_OK=0
        fi
    fi
done

# Light DB roundtrip.
if ! sudo -u postgres psql -tAc "SELECT 1" -d "${PG_DB_NAME:-aipanel}" >/dev/null 2>&1; then
    log_error "Database roundtrip failed"
    ALL_OK=0
fi

if (( ! ALL_OK )); then
    false   # trigger ERR trap → rollback
fi

# ---------------------------------------------------------------------------
# Prune old backups
# ---------------------------------------------------------------------------
if (( ! DRY_RUN )) && [[ -d "${UPDATE_BACKUP_DIR}" ]]; then
    log_step "Pruning backups (keeping last ${KEEP})"
    # Keep newest ${KEEP} of each kind.
    for prefix in pre-update-*-config.tar.gz pre-update-*.sql.gz; do
        # shellcheck disable=SC2012
        ls -1t "${UPDATE_BACKUP_DIR}"/${prefix} 2>/dev/null \
            | tail -n +"$((KEEP + 1))" \
            | while read -r f; do
                log_info "  removing $(basename "${f}")"
                rm -f "${f}"
            done
    done
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
trap - ERR
NEW_VERSION="$(current_version)"
log_info ""
log_info "Updated ${CURRENT_VERSION} → ${NEW_VERSION} (${TARGET_SHA:0:12})"
log_info "Previous SHA recorded at ${UPDATE_PREV_VERSION_FILE}"
