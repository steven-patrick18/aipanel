#!/usr/bin/env bash
# installer/lib/migrate.sh — schema migration runner.
#
# Tracks applied migrations in a `schema_migrations` table:
#   version     text PRIMARY KEY     -- numeric prefix, e.g. "001"
#   name        text                 -- file basename without .sql
#   checksum    text                 -- sha256 of the up file
#   applied_at  timestamptz          -- now()
#
# Every migration runs inside a single transaction (psql --single-transaction)
# so any failure rolls back both the schema change and the schema_migrations
# bookkeeping row.
#
# Public functions:
#   migrate_up                 - apply all pending migrations
#   migrate_status             - print applied + pending
#   migrate_to <version>       - bring DB to exactly <version> (forward or back)

set -euo pipefail

MIGRATIONS_DIR="${MIGRATIONS_DIR:-${AIPANEL_PREFIX}/installer/migrations}"
MIG_DB_NAME="${MIG_DB_NAME:-${PG_DB_NAME:-aipanel}}"
MIG_PG_OS_USER="${MIG_PG_OS_USER:-postgres}"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# mig_psql — runs psql as the postgres OS user against MIG_DB_NAME.
mig_psql() {
    sudo -u "${MIG_PG_OS_USER}" psql -v ON_ERROR_STOP=1 -d "${MIG_DB_NAME}" "$@"
}

# mig_init — create schema_migrations table if missing.
mig_init() {
    mig_psql -q -c "
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     text PRIMARY KEY,
            name        text NOT NULL,
            checksum    text NOT NULL,
            applied_at  timestamptz NOT NULL DEFAULT now()
        );
    " >/dev/null
}

# mig_version_of <path> — extract leading numeric prefix from filename.
mig_version_of() {
    basename "$1" | grep -oE '^[0-9]+' | head -n1
}

# mig_name_of <path> — basename minus .sql / .down.sql.
mig_name_of() {
    local b
    b="$(basename "$1")"
    b="${b%.down.sql}"
    b="${b%.sql}"
    echo "${b}"
}

# mig_checksum <path>
mig_checksum() {
    sha256sum "$1" | awk '{print $1}'
}

# mig_files_up — sorted list of forward migration paths.
mig_files_up() {
    [[ -d "${MIGRATIONS_DIR}" ]] || return 0
    find "${MIGRATIONS_DIR}" -maxdepth 1 -type f -name '[0-9]*_*.sql' \
         ! -name '*.down.sql' | LC_ALL=C sort
}

# mig_down_for <up_path> — companion .down.sql path. May not exist.
mig_down_for() {
    local up="$1" dir base
    dir="$(dirname "${up}")"
    base="$(basename "${up}" .sql)"
    echo "${dir}/${base}.down.sql"
}

# mig_applied_csv — comma-bookended string of applied versions for fast
# "is X applied" lookups via shell pattern matching.
mig_applied_csv() {
    local list
    list="$(mig_psql -tAq -c \
        "SELECT version FROM schema_migrations ORDER BY version;" 2>/dev/null \
        | tr '\n' ',')"
    echo ",${list}"
}

# mig_apply_one <up_path>
mig_apply_one() {
    local file="$1" version name checksum
    version="$(mig_version_of "${file}")"
    name="$(mig_name_of "${file}")"
    checksum="$(mig_checksum "${file}")"

    log_info "Applying migration ${version}: ${name}"
    {
        cat "${file}"
        printf "\nINSERT INTO schema_migrations (version, name, checksum) VALUES ('%s', '%s', '%s');\n" \
            "${version}" "${name}" "${checksum}"
    } | sudo -u "${MIG_PG_OS_USER}" psql \
            -v ON_ERROR_STOP=1 \
            --single-transaction \
            -d "${MIG_DB_NAME}" >/dev/null
}

# mig_revert_one <up_path> — applies the .down.sql and removes the row.
mig_revert_one() {
    local up="$1" down version
    down="$(mig_down_for "${up}")"
    version="$(mig_version_of "${up}")"

    if [[ ! -f "${down}" ]]; then
        die "Cannot revert ${version}: missing down migration at ${down}"
    fi

    log_warn "Reverting migration ${version}"
    {
        cat "${down}"
        printf "\nDELETE FROM schema_migrations WHERE version = '%s';\n" \
            "${version}"
    } | sudo -u "${MIG_PG_OS_USER}" psql \
            -v ON_ERROR_STOP=1 \
            --single-transaction \
            -d "${MIG_DB_NAME}" >/dev/null
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# migrate_up — apply every pending migration in version order.
migrate_up() {
    mig_init
    local applied
    applied="$(mig_applied_csv)"

    local file version pending=0
    while IFS= read -r file; do
        [[ -z "${file}" ]] && continue
        version="$(mig_version_of "${file}")"
        if [[ "${applied}" == *",${version},"* ]]; then
            log_debug "Already applied: ${version}"
            continue
        fi
        mig_apply_one "${file}"
        pending=$((pending + 1))
    done < <(mig_files_up)

    if (( pending == 0 )); then
        log_info "No pending migrations."
    else
        log_info "Applied ${pending} migration(s)."
    fi
}

# migrate_status — table of applied / pending migrations.
migrate_status() {
    mig_init
    local applied
    applied="$(mig_applied_csv)"

    printf '%-10s %-10s %s\n' "VERSION" "STATUS" "NAME"
    local file version name
    while IFS= read -r file; do
        [[ -z "${file}" ]] && continue
        version="$(mig_version_of "${file}")"
        name="$(mig_name_of "${file}")"
        if [[ "${applied}" == *",${version},"* ]]; then
            printf '%-10s %-10s %s\n' "${version}" "applied" "${name}"
        else
            printf '%-10s %-10s %s\n' "${version}" "pending" "${name}"
        fi
    done < <(mig_files_up)
}

# migrate_to <version> — bring the database to exactly <version>.
# Versions strictly less-or-equal to <version> are applied if missing;
# versions strictly greater are reverted using their .down.sql.
migrate_to() {
    local target="${1:-}"
    [[ -n "${target}" ]] || die "migrate_to: target version required (e.g. 001)"
    mig_init

    # Read all up files into an array.
    local files=() f
    while IFS= read -r f; do
        [[ -z "${f}" ]] && continue
        files+=("${f}")
    done < <(mig_files_up)

    # Validate target exists in the file set.
    local found=0 v
    for f in "${files[@]}"; do
        v="$(mig_version_of "${f}")"
        if [[ "${v}" == "${target}" ]]; then found=1; break; fi
    done
    (( found )) || die "Target version ${target} not present in ${MIGRATIONS_DIR}"

    # Forward pass: apply everything <= target that is not yet applied.
    local applied
    applied="$(mig_applied_csv)"
    for f in "${files[@]}"; do
        v="$(mig_version_of "${f}")"
        if [[ "${applied}" != *",${v},"* ]]; then
            # Lexicographic comparison works for zero-padded numeric prefixes.
            if [[ "${v}" < "${target}" || "${v}" == "${target}" ]]; then
                mig_apply_one "${f}"
            fi
        fi
    done

    # Reverse pass: revert anything > target that IS applied.
    applied="$(mig_applied_csv)"
    local i
    for ((i=${#files[@]}-1; i>=0; i--)); do
        f="${files[i]}"
        v="$(mig_version_of "${f}")"
        if [[ "${applied}" == *",${v},"* ]] && [[ "${v}" > "${target}" ]]; then
            mig_revert_one "${f}"
        fi
    done
}
