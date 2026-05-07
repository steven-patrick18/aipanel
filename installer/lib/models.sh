#!/usr/bin/env bash
# installer/lib/models.sh — download / extract model weights for the three servers.
#
# Two modes, selected by AIPANEL_MODELS_SOURCE:
#   online (default) — fetch from HuggingFace (or HF mirror via HF_ENDPOINT)
#   airgap           — extract from /opt/aipanel/airgap-bundle/models.tar.gz
#
# Idempotent. Each model directory is checked for a sentinel file; present →
# skipped, absent → fetched / extracted.

set -euo pipefail

AIPANEL_MODELS_DIR="${AIPANEL_MODELS_DIR:-/var/lib/aipanel/models}"
AIPANEL_MODELS_SOURCE="${AIPANEL_MODELS_SOURCE:-online}"
AIPANEL_MODELS_AIRGAP_BUNDLE="${AIPANEL_MODELS_AIRGAP_BUNDLE:-/opt/aipanel/airgap-bundle/models.tar.gz}"

# Defaults — operator can override per-call.
LLM_MODEL_ID="${LLM_MODEL_ID:-Qwen/Qwen2.5-14B-Instruct-AWQ}"
STT_MODEL_ID="${STT_MODEL_ID:-Systran/faster-whisper-large-v3}"
TTS_MODEL_ID="${TTS_MODEL_ID:-SWivid/F5-TTS}"

# huggingface-cli lives in whichever venv we hand to models_install_hf_cli.
# We install it into the LLM venv since it's always present.
MODELS_HF_VENV="${MODELS_HF_VENV:-/opt/aipanel/llm-server/.venv}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# models_local_path <kind> <hf_id> — folder name = id with '/' → '__'
models_local_path() {
    local kind="$1" hf_id="$2"
    echo "${AIPANEL_MODELS_DIR}/${kind}/${hf_id//\//__}"
}

# models_present <path>
models_present() {
    local p="$1"
    [[ -d "${p}" ]] && find "${p}" -mindepth 1 -maxdepth 2 -type f -print -quit \
        | grep -q .
}

models_install_hf_cli() {
    if [[ -x "${MODELS_HF_VENV}/bin/huggingface-cli" ]]; then
        return 0
    fi
    if [[ ! -x "${MODELS_HF_VENV}/bin/pip" ]]; then
        die "HF venv not found at ${MODELS_HF_VENV}; build the LLM venv first"
    fi
    log_info "Installing huggingface_hub into ${MODELS_HF_VENV}"
    sudo -u "${AIPANEL_USER}" -H \
        "${MODELS_HF_VENV}/bin/pip" install --quiet 'huggingface_hub[cli]>=0.23'
}

# models_hf_download <hf_id> <local_dir> — uses huggingface-cli download.
models_hf_download() {
    local hf_id="$1" local_dir="$2"
    models_install_hf_cli
    log_info "Downloading ${hf_id} → ${local_dir}"
    install -d -m 0755 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" \
        "$(dirname "${local_dir}")"
    sudo -u "${AIPANEL_USER}" -H \
        HF_HUB_DOWNLOAD_TIMEOUT=600 \
        "${MODELS_HF_VENV}/bin/huggingface-cli" download "${hf_id}" \
        --local-dir "${local_dir}" \
        --local-dir-use-symlinks False
}

# models_airgap_extract — first call extracts the bundle into the models dir.
# The bundle is a tar.gz of the same {llm,stt,tts}/<id-with-__> layout we
# produce online, so post-extract sentinel checks succeed identically.
models_airgap_extract() {
    if [[ ! -f "${AIPANEL_MODELS_AIRGAP_BUNDLE}" ]]; then
        die "airgap bundle missing: ${AIPANEL_MODELS_AIRGAP_BUNDLE}"
    fi
    if [[ -f "${AIPANEL_MODELS_DIR}/.airgap-extracted" ]]; then
        log_debug "airgap bundle already extracted"
        return 0
    fi
    log_info "Extracting airgap bundle ${AIPANEL_MODELS_AIRGAP_BUNDLE}"
    install -d -m 0755 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" \
        "${AIPANEL_MODELS_DIR}"
    tar -xzf "${AIPANEL_MODELS_AIRGAP_BUNDLE}" -C "${AIPANEL_MODELS_DIR}"
    chown -R "${AIPANEL_USER}:${AIPANEL_GROUP}" "${AIPANEL_MODELS_DIR}"
    : > "${AIPANEL_MODELS_DIR}/.airgap-extracted"
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

models_setup_dir() {
    install -d -m 0755 -o "${AIPANEL_USER}" -g "${AIPANEL_GROUP}" \
        "${AIPANEL_MODELS_DIR}" \
        "${AIPANEL_MODELS_DIR}/llm" \
        "${AIPANEL_MODELS_DIR}/stt" \
        "${AIPANEL_MODELS_DIR}/tts" \
        "${AIPANEL_MODELS_DIR}/hf-cache"
}

# models_download_one <kind> <hf_id>
models_download_one() {
    local kind="$1" hf_id="$2" target
    target="$(models_local_path "${kind}" "${hf_id}")"
    if models_present "${target}"; then
        log_debug "model already present: ${target}"
        return 0
    fi
    case "${AIPANEL_MODELS_SOURCE}" in
        online)
            models_hf_download "${hf_id}" "${target}"
            ;;
        airgap)
            models_airgap_extract
            if ! models_present "${target}"; then
                die "model ${hf_id} missing from airgap bundle (expected at ${target})"
            fi
            ;;
        *)
            die "AIPANEL_MODELS_SOURCE must be 'online' or 'airgap', got: ${AIPANEL_MODELS_SOURCE}"
            ;;
    esac
}

models_download_llm() { models_download_one llm "${LLM_MODEL_ID}"; }
models_download_stt() { models_download_one stt "${STT_MODEL_ID}"; }
models_download_tts() { models_download_one tts "${TTS_MODEL_ID}"; }

models_download_all() {
    models_setup_dir
    models_download_llm
    models_download_stt
    models_download_tts
    log_info "Models present under ${AIPANEL_MODELS_DIR}"
}
