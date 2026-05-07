#!/usr/bin/env bash
# installer/lib/join.sh — bring a new node into an existing aipanel
# cluster. Sourced by install.sh when --join=<token> is passed.
#
# What it does (vs a normal install):
#   - SKIPS local Postgres / Redis / MinIO install (uses the primary's)
#   - SKIPS bootstrap admin (already exists on the primary)
#   - SKIPS migration runner (primary already migrated)
#   - POSTs the join token to the primary, gets cluster config back
#   - Writes /etc/aipanel/aipanel.conf pointing at the primary's services
#   - Installs ONLY the services for this node's role (gpu / app / sip)
#   - Starts heartbeating into the shared `nodes` table

set -euo pipefail

# Required globals from install.sh: AIPANEL_PREFIX, AIPANEL_USER, AIPANEL_GROUP,
#   AIP_JOIN_TOKEN, AIP_JOIN_PRIMARY (URL), AIP_JOIN_ROLE (gpu|app|sip|mixed)

join_validate_args() {
    [[ -n "${AIP_JOIN_TOKEN:-}" ]]    || die "--join requires a token (--join=AIPANEL-...)"
    [[ -n "${AIP_JOIN_PRIMARY:-}" ]]  || die "--join requires --primary=<panel-url>"
    [[ -n "${AIP_JOIN_ROLE:-}" ]]     || AIP_JOIN_ROLE="mixed"
    case "${AIP_JOIN_ROLE}" in
        gpu|app|sip|mixed) ;;
        *) die "Invalid --role=${AIP_JOIN_ROLE}. Must be gpu | app | sip | mixed." ;;
    esac
}

join_call_primary() {
    log_step "Calling primary at ${AIP_JOIN_PRIMARY}/api/v1/cluster/join"
    local body
    body="$(printf '{"token":"%s","hostname":"%s"}' \
              "${AIP_JOIN_TOKEN}" "$(hostname -f)")"
    local resp http_code
    resp="$(mktemp)"
    http_code="$(curl -sS -w '%{http_code}' -o "${resp}" \
        -X POST -H 'Content-Type: application/json' \
        -d "${body}" \
        "${AIP_JOIN_PRIMARY%/}/api/v1/cluster/join")"
    if [[ "${http_code}" != "200" ]]; then
        log_error "Primary returned HTTP ${http_code}"
        cat "${resp}" | sed 's/^/    /'
        rm -f "${resp}"
        die "Join failed"
    fi
    AIP_JOIN_RESPONSE="$(cat "${resp}")"
    rm -f "${resp}"
    log_info "Primary accepted the token; cluster config received."
}

join_render_config() {
    log_step "Writing /etc/aipanel/aipanel.conf for joined node"
    install -d -m 0755 -o root -g "${AIPANEL_GROUP}" /etc/aipanel
    # Use python (bundled with Ubuntu) to render the config from the
    # JSON the primary returned. Avoids hand-rolled jq dependencies.
    AIP_JOIN_RESPONSE="${AIP_JOIN_RESPONSE}" python3 - <<'PY' > /etc/aipanel/aipanel.conf
import json, os, textwrap
data = json.loads(os.environ["AIP_JOIN_RESPONSE"])
cfg = data["cluster_config"]
print(textwrap.dedent(f"""
[database]
host = "{cfg['database']['host']}"
port = {cfg['database']['port']}
name = "{cfg['database']['name']}"
user = "{cfg['database']['user']}"

[redis]
host = "{cfg['redis']['host']}"
port = {cfg['redis']['port']}
db   = {cfg['redis']['db']}

[minio]
endpoint = "{cfg['minio']['endpoint']}"
secure   = {str(cfg['minio']['secure']).lower()}
bucket_recordings  = "{cfg['minio']['bucket_recordings']}"
bucket_transcripts = "{cfg['minio']['bucket_transcripts']}"
bucket_kb          = "{cfg['minio']['bucket_kb']}"
bucket_voices      = "{cfg['minio']['bucket_voices']}"

[panel]
public_url = "{cfg['panel_public_url']}"
listen_host = "127.0.0.1"
listen_port = 8000

[cluster]
node_role = "{data['role']}"
hostname  = "{__import__('socket').getfqdn()}"
heartbeat_interval_sec = 10
""").lstrip())
PY
    chmod 0640 /etc/aipanel/aipanel.conf
    chown root:"${AIPANEL_GROUP}" /etc/aipanel/aipanel.conf
}

join_prompt_secrets() {
    log_step "Secrets bootstrap"
    log_info "The new node needs the same secrets.env as the primary"
    log_info "(DB_PASSWORD, REDIS_PASSWORD, MINIO_ACCESS_KEY/SECRET_KEY,"
    log_info " JWT_SECRET, ENCRYPTION_KEY)."
    log_info ""
    log_info "Copy /etc/aipanel/secrets.env from the primary to this box now."
    log_info "Press ENTER once it's in place at /etc/aipanel/secrets.env, or"
    log_info "Ctrl-C to abort."
    read -r _
    [[ -f /etc/aipanel/secrets.env ]] \
        || die "/etc/aipanel/secrets.env still missing — abort."
    chmod 0640 /etc/aipanel/secrets.env
    chown root:"${AIPANEL_GROUP}" /etc/aipanel/secrets.env
}

join_install_services_for_role() {
    log_step "Installing services for role: ${AIP_JOIN_ROLE}"
    local LIB="${AIPANEL_PREFIX}/installer/lib"
    case "${AIP_JOIN_ROLE}" in
        gpu)
            . "${LIB}/llm.sh"     && llm_setup
            . "${LIB}/stt.sh"     && stt_setup
            . "${LIB}/tts.sh"     && tts_setup
            ;;
        app)
            . "${LIB}/panel.sh"   && panel_setup
            . "${LIB}/workers.sh" && workers_setup
            . "${LIB}/session_mgr.sh" && session_mgr_setup
            ;;
        sip)
            . "${LIB}/sip.sh"     && sip_setup
            ;;
        mixed)
            for s in panel workers session_mgr sip llm stt tts; do
                . "${LIB}/${s}.sh" && "${s}_setup"
            done
            ;;
    esac
}

join_register_systemd() {
    log_step "Enabling + starting installed services"
    systemctl daemon-reload
    case "${AIP_JOIN_ROLE}" in
        gpu)   systemctl enable --now aipanel-llm aipanel-stt aipanel-tts ;;
        app)   systemctl enable --now aipanel-web aipanel-jobs aipanel-workers \
                                    aipanel-session-mgr ;;
        sip)   systemctl enable --now aipanel-sip ;;
        mixed) systemctl enable --now aipanel-web aipanel-jobs aipanel-workers \
                                    aipanel-session-mgr aipanel-sip \
                                    aipanel-llm aipanel-stt aipanel-tts ;;
    esac
}

join_run() {
    join_validate_args
    join_call_primary
    join_render_config
    join_prompt_secrets
    join_install_services_for_role
    join_register_systemd
    log_info ""
    log_info "Node joined cluster as role=${AIP_JOIN_ROLE}."
    log_info "Check Cluster page on the primary — this hostname should appear shortly."
}
