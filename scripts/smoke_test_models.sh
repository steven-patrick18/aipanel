#!/usr/bin/env bash
# scripts/smoke_test_models.sh — quick health + round-trip check for the
# three model services. Safe to run on a live host; uses /tmp for fixtures
# and never writes outside it.
#
# Exit codes:
#   0 — all three services passed
#   1 — at least one failure (details printed)
#
# Env overrides:
#   LLM_URL, STT_URL, TTS_URL — base URLs; default to the configured loopback ports
#   LLM_MODEL                 — for the chat completion's model field
#   TTS_VOICE_ID              — voice id for synthesize; if unset and the
#                               default backend requires one, the synth check
#                               is skipped (with a warning, not a failure)

set -euo pipefail

LLM_URL="${LLM_URL:-http://127.0.0.1:8001}"
STT_URL="${STT_URL:-http://127.0.0.1:8002}"
TTS_URL="${TTS_URL:-http://127.0.0.1:8003}"
LLM_MODEL="${LLM_MODEL:-Qwen/Qwen2.5-14B-Instruct-AWQ}"
TTS_VOICE_ID="${TTS_VOICE_ID:-}"

PY="${PY:-python3}"
TMPDIR="$(mktemp -d -t aipanel-smoke.XXXXXX)"
trap 'rm -rf "${TMPDIR}"' EXIT

# ---- pretty output ---------------------------------------------------------
if [[ -t 1 ]]; then
    GREEN=$'\033[32m'; RED=$'\033[31m'; YEL=$'\033[33m'; RESET=$'\033[0m'
else
    GREEN=""; RED=""; YEL=""; RESET=""
fi
PASS=0; FAIL=0; SKIP=0

ok()   { printf "%s[PASS]%s %s\n" "${GREEN}" "${RESET}" "$*"; PASS=$((PASS+1)); }
bad()  { printf "%s[FAIL]%s %s\n" "${RED}"   "${RESET}" "$*"; FAIL=$((FAIL+1)); }
skip() { printf "%s[SKIP]%s %s\n" "${YEL}"   "${RESET}" "$*"; SKIP=$((SKIP+1)); }

# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------

check_health() {
    local name="$1" url="$2"
    local body code
    body="$(curl -sS -o "${TMPDIR}/${name}-health.json" -w '%{http_code}' \
              "${url}/health" || echo 000)"
    code="${body: -3}"
    if [[ "${code}" == "200" ]]; then
        ok "${name} /health -> 200"
    else
        bad "${name} /health -> HTTP ${code}; body:"
        sed 's/^/      /' "${TMPDIR}/${name}-health.json" 2>/dev/null || true
    fi
}

# ---------------------------------------------------------------------------
# LLM round trip
# ---------------------------------------------------------------------------

check_llm_chat() {
    local body
    body="$(curl -sS -X POST "${LLM_URL}/v1/chat/completions" \
        -H 'Content-Type: application/json' \
        -d "$(cat <<EOF
{
  "model": "${LLM_MODEL}",
  "messages": [{"role":"user","content":"Reply with the single word: pong"}],
  "max_tokens": 8,
  "temperature": 0
}
EOF
)" || true)"
    if echo "${body}" | grep -qi 'pong'; then
        ok "LLM chat completion returned 'pong'"
    elif echo "${body}" | grep -q '"choices"'; then
        ok "LLM chat completion responded (model output not literally 'pong'; that's OK)"
    else
        bad "LLM chat completion did not return choices:"
        echo "${body}" | head -c 400 | sed 's/^/      /'
    fi
}

# ---------------------------------------------------------------------------
# STT round trip — generate a 1 s 440 Hz WAV and POST it
# ---------------------------------------------------------------------------

generate_test_wav() {
    local out="$1"
    "${PY}" - "$out" <<'PYEOF'
import math, struct, sys, wave
out = sys.argv[1]
sr = 16000
secs = 1.0
amp = 0.2
samples = [int(amp * 32767 * math.sin(2*math.pi*440*t/sr)) for t in range(int(sr*secs))]
with wave.open(out, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(sr)
    w.writeframes(b"".join(struct.pack("<h", s) for s in samples))
PYEOF
}

check_stt_transcribe() {
    local wav="${TMPDIR}/test.wav"
    if ! generate_test_wav "${wav}"; then
        bad "could not generate test WAV (python3 missing?)"
        return
    fi
    local body
    body="$(curl -sS -X POST "${STT_URL}/v1/stt/transcribe" \
        -F "audio=@${wav};type=audio/wav" \
        -F "language=en" || true)"
    if echo "${body}" | grep -q '"text"'; then
        ok "STT transcribe returned a JSON text field"
    else
        bad "STT transcribe did not return text:"
        echo "${body}" | head -c 400 | sed 's/^/      /'
    fi
}

# ---------------------------------------------------------------------------
# TTS round trip — POST synthesize, verify first audio bytes arrive
# ---------------------------------------------------------------------------

check_tts_synth() {
    if [[ -z "${TTS_VOICE_ID}" ]]; then
        skip "TTS synth: TTS_VOICE_ID unset (set it or use noop backend)"
        return
    fi
    local out="${TMPDIR}/synth.bin"
    local code
    code="$(curl -sS -o "${out}" -w '%{http_code}' \
        -X POST "${TTS_URL}/v1/tts/synthesize" \
        -H 'Content-Type: application/json' \
        -d "{\"text\":\"hello world\",\"voice_id\":\"${TTS_VOICE_ID}\",\"output_format\":\"ulaw_8000\"}" \
        || echo 000)"
    if [[ "${code}" == "200" ]] && [[ -s "${out}" ]]; then
        local sz
        sz="$(wc -c < "${out}" | tr -d ' ')"
        ok "TTS synthesize returned ${sz} bytes of audio"
    else
        bad "TTS synthesize -> HTTP ${code}, $(stat -c %s "${out}" 2>/dev/null || echo 0) bytes"
    fi
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

echo "==> Health"
check_health LLM "${LLM_URL}"
check_health STT "${STT_URL}"
check_health TTS "${TTS_URL}"

echo
echo "==> Round-trip"
check_llm_chat
check_stt_transcribe
check_tts_synth

echo
echo "Result: ${PASS} pass, ${FAIL} fail, ${SKIP} skip"
[[ "${FAIL}" -eq 0 ]] || exit 1
