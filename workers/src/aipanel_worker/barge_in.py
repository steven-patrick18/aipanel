"""Barge-in detection — should we cancel TTS to listen to the user?

The decision is a pure function of the latest STT partial + the speaking
state. The orchestrator wires up the side effects (cancel TTS, drain audio_out
queue, mark a barge-in metric).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BargeInDecision:
    cancel_tts: bool
    reason: str


def should_barge_in(
    *,
    partial_text: str,
    partial_stability: float,
    partial_duration_ms: float,
    is_speaking: bool,
    min_words: int = 3,
    min_duration_ms: float = 800.0,
    stability_threshold: float = 0.6,
) -> BargeInDecision:
    """Decide whether the agent should yield to the user.

    Rules (all must hold to barge in):

    * The agent is currently producing TTS audio (``is_speaking``).
    * The partial transcript is stable enough not to be model jitter
      (``partial_stability >= stability_threshold``).
    * The partial is long enough not to be a backchannel acknowledgement —
      ≥ ``min_words`` words AND ≥ ``min_duration_ms``. Both gates apply
      because someone saying "no I really don't think so" in 700 ms is still
      a real interruption.
    """
    if not is_speaking:
        return BargeInDecision(False, "agent_silent")
    if not partial_text:
        return BargeInDecision(False, "empty_partial")
    if partial_stability < stability_threshold:
        return BargeInDecision(False, "low_stability")

    word_count = len([w for w in partial_text.split() if w.strip()])
    if word_count < min_words and partial_duration_ms < min_duration_ms:
        return BargeInDecision(False, "backchannel_filtered")

    return BargeInDecision(True, "user_interrupting")
