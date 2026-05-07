"""Prometheus metrics for the worker process. Module-level so any
component can `from .metrics import M_FOO` and increment without ceremony.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

M_ACTIVE = Gauge(
    "aipanel_worker_active_calls",
    "Concurrently-active call sessions",
)

M_CALLS = Counter(
    "aipanel_worker_calls_total",
    "Calls handled, by terminal outcome",
    ["outcome"],
)

# LLM latency split by stage so we can see first-token vs end-to-end.
M_LLM_LATENCY = Histogram(
    "aipanel_worker_llm_latency_seconds",
    "LLM request latency (per stage)",
    ["stage"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)

M_STT_FINAL_LATENCY = Histogram(
    "aipanel_worker_stt_final_latency_seconds",
    "Time from end-of-speech to final transcript",
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

M_TTS_FIRST_BYTE = Histogram(
    "aipanel_worker_tts_first_byte_seconds",
    "Time from synthesize request to first audio byte",
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

M_BARGE_INS = Counter(
    "aipanel_worker_barge_ins_total",
    "Times the user interrupted the agent and we cancelled TTS",
)

M_TOOL_CALLS = Counter(
    "aipanel_worker_tool_calls_total",
    "LLM tool invocations",
    ["tool"],
)

M_LLM_ERRORS = Counter(
    "aipanel_worker_llm_errors_total",
    "LLM call failures (timeout, 5xx, bad-shape)",
    ["kind"],
)

M_AUDIO_DROPS = Counter(
    "aipanel_worker_audio_frames_dropped_total",
    "Audio frames dropped due to queue overflow",
    ["direction"],          # in | out
)
