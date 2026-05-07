#!/usr/bin/env bash
# install.sh — aipanel on-prem installer entrypoint.
#
# v0.1.0 scope: preflight, OS user, base dirs, OS packages. Application
# services land in subsequent prompts. Safe to re-run.

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve our own location so we can be invoked via absolute path, relative
# path, or symlink without breaking source paths.
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/installer/lib"

if [[ ! -d "${LIB_DIR}" ]]; then
    echo "ERROR: cannot find installer libraries at ${LIB_DIR}" >&2
    exit 1
fi

# Source common.sh first — it defines logging, paths, and the error trap.
# shellcheck source=installer/lib/common.sh
. "${LIB_DIR}/common.sh"

# Source the rest in dependency order. common.sh must come first; preflight
# must come before deps (it sets AIPANEL_OS_ID); the rest are independent.
for module in preflight.sh deps.sh user.sh secrets.sh config.sh \
              postgres.sh migrate.sh redis.sh minio.sh \
              nvidia.sh python_env.sh nodejs.sh \
              pjsip.sh sip.sh \
              models.sh llm.sh stt.sh tts.sh embed.sh \
              workers.sh \
              session_mgr.sh \
              panel.sh frontend.sh nginx.sh \
              ops.sh \
              join.sh; do
    # shellcheck disable=SC1090
    . "${LIB_DIR}/${module}"
done

# ---------------------------------------------------------------------------
# Argument parsing — we accept a small surface so we can be invoked in
# "join an existing cluster" mode by the curl-pipe install snippet the
# panel UI generates.
# ---------------------------------------------------------------------------
AIP_JOIN_TOKEN=""
AIP_JOIN_PRIMARY=""
AIP_JOIN_ROLE=""
for arg in "$@"; do
    case "$arg" in
        --token=*)   AIP_JOIN_TOKEN="${arg#*=}" ;;
        --primary=*) AIP_JOIN_PRIMARY="${arg#*=}" ;;
        --role=*)    AIP_JOIN_ROLE="${arg#*=}" ;;
        --help|-h)   sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        "") ;;
        *) ;;  # silently ignore unknowns; join.sh validates its own
    esac
done
export AIP_JOIN_TOKEN AIP_JOIN_PRIMARY AIP_JOIN_ROLE

# ---------------------------------------------------------------------------
# Logging — we tee everything to /var/log/aipanel/install.log. The log dir
# must exist before tee can write to it, and we must run as root before we
# can create it; check root first.
# ---------------------------------------------------------------------------
require_root
init_log_dir

# Re-exec ourselves with stdout+stderr tee'd to the log file. The
# AIPANEL_LOGGING_INITIALIZED guard prevents an infinite re-exec loop.
if [[ -z "${AIPANEL_LOGGING_INITIALIZED:-}" ]]; then
    export AIPANEL_LOGGING_INITIALIZED=1
    # 'tee -a' appends; '2>&1' merges stderr so colored warnings still
    # appear in the file. The 'exec' replaces this shell with the piped
    # command so signal handling stays clean.
    exec > >(tee -a "${AIPANEL_LOG_FILE}") 2>&1
fi

# Install the error trap NOW that logging is up.
trap 'aip_on_error $? "${BASH_COMMAND}" "${BASH_SOURCE[0]}:${LINENO}"' ERR

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
VERSION_STRING="$(cat "${SCRIPT_DIR}/VERSION" 2>/dev/null || echo unknown)"
log_info "aipanel installer v${VERSION_STRING}"
log_info "Log file: ${AIPANEL_LOG_FILE}"

# ---------------------------------------------------------------------------
# Concurrency guard
# ---------------------------------------------------------------------------
acquire_install_lock

# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
log_step "Preflight checks"
pf_run_all

log_step "Create system user and base directories"
user_create
user_setup_dirs
# Re-chown the log dir now that the user exists.
chown "${AIPANEL_USER}:${AIPANEL_GROUP}" "${AIPANEL_LOG_DIR}"

log_step "Install OS packages"
deps_install_all

# ---------------------------------------------------------------------------
# Branch: cluster-join mode (--token=...) skips the rest of the primary
# install and runs the join orchestration instead.
# ---------------------------------------------------------------------------
if [[ -n "${AIP_JOIN_TOKEN}" ]]; then
    log_step "Cluster-join mode — skipping primary infra install"
    join_run
    log_info ""
    log_info "Done. This node is now part of the cluster."
    exit 0
fi

# Generate /etc/aipanel/secrets.env on first install. After this point the
# DB / Redis / MinIO / JWT / encryption secrets are available in $ENV.
log_step "Generate secrets"
secrets_generate
# Top up new keys added in later versions without rotating existing ones.
secrets_ensure_field SESSION_MGR_TOKEN secrets_hex32
secrets_load

log_step "Render aipanel.conf from template"
config_render

log_step "Configure PostgreSQL (install + role + database)"
pg_configure

log_step "Apply schema migrations"
migrate_up

# Verify the GPU/CUDA stack only if a GPU was detected during preflight.
# This is non-fatal on dev boxes (AIPANEL_HAS_GPU=0) and silent there.
log_step "Verify NVIDIA / CUDA stack"
nvidia_verify_all

log_step "Build PJSIP and install SIP service"
sip_setup

log_step "Install model servers (LLM, STT, TTS, embed)"
# LLM venv must exist first so models.sh can install huggingface_hub into it.
llm_setup
stt_setup
tts_setup
embed_setup

log_step "Download model weights (mode: ${AIPANEL_MODELS_SOURCE:-online})"
models_download_all
EMBED_MODEL_ID="${EMBED_MODEL_ID:-BAAI/bge-m3}" \
    models_download_one embed "${EMBED_MODEL_ID:-BAAI/bge-m3}"

log_step "Install conversation workers"
workers_setup

log_step "Install ViciDial Session Manager"
session_mgr_setup

log_step "Install panel backend (web + jobs services)"
panel_setup

log_step "Build panel frontend (Vite SPA)"
frontend_setup

log_step "Configure nginx (HTTPS, SPA + API proxy)"
nginx_setup

log_step "Install operational tooling (aipanelctl + nightly backup cron)"
ops_setup

# Remaining service configuration is deferred to later prompts. Uncomment
# as the matching modules become production-ready.
#
# log_step "Configure Redis"
# redis_configure
#
# log_step "Configure MinIO"
# minio_configure
#
# log_step "Provision Python venv"
# py_setup
#
# log_step "Build frontend"
# node_setup

log_info ""
log_info "Database ready at: postgresql://${PG_DB_USER}@127.0.0.1:5432/${PG_DB_NAME}"
log_info "Config:    ${AIPANEL_ETC}/aipanel.conf"
log_info "Secrets:   ${AIPANEL_ETC}/secrets.env (mode 0600, owner ${AIPANEL_USER})"
log_info "SIP:       systemctl status aipanel-sip.service   (enabled, NOT started)"
log_info "LLM:       systemctl status aipanel-llm.service   (enabled, NOT started)"
log_info "STT:       systemctl status aipanel-stt.service   (enabled, NOT started)"
log_info "TTS:       systemctl status aipanel-tts.service   (enabled, NOT started)"
log_info "Workers:   systemctl status aipanel-workers.service (enabled, NOT started)"
log_info "Vici:      systemctl status aipanel-session-mgr.service (enabled, NOT started)"
log_info "Web API:   systemctl status aipanel-web.service (enabled, NOT started)"
log_info "Jobs:      systemctl status aipanel-jobs.service (enabled, NOT started)"
log_info "nginx:     https://$(hostname -f 2>/dev/null || hostname) (self-signed cert; replace in /etc/aipanel/ssl/)"
log_info "Control:   aipanelctl status | aipanelctl logs <svc> | aipanelctl backup"
log_info "Smoke:     bash ${AIPANEL_PREFIX}/scripts/smoke_test_models.sh"
log_info ""
log_info "Installation v0.9.0 complete. Operational tooling now installed."
