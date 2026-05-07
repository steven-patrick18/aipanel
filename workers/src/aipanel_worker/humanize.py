"""Pure-function helpers that make the agent feel less robotic.

Everything in this module is deterministic-given-rng so the unit tests can
seed and assert exact behaviour.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Openers
# ---------------------------------------------------------------------------

def pick_opener(openers: list[str], rng: random.Random | None = None) -> str:
    """Pick one opening line. Empty input → empty string (caller handles)."""
    if not openers:
        return ""
    r = rng or random
    return r.choice(openers)


# ---------------------------------------------------------------------------
# Filler injection
# ---------------------------------------------------------------------------

# Small, intentionally bland — these go through TTS which will add prosody.
_FILLERS = (
    "um, ",
    "uh, ",
    "let me see, ",
    "right, so ",
    "okay, ",
    "well, ",
)


def inject_filler(
    text: str,
    *,
    frequency: float,
    turns_since_last: int,
    min_gap_turns: int = 4,
    rng: random.Random | None = None,
) -> tuple[str, bool]:
    """Possibly prepend a filler word to ``text``.

    Returns ``(maybe_modified_text, did_inject)``. Injection is gated by:

    * ``frequency`` — probability of injection per eligible turn (0..1)
    * ``turns_since_last`` — only inject if ≥ ``min_gap_turns`` turns have
      passed since the last filler. Prevents back-to-back "um, um, um".
    * Empty / very short text — skip.
    """
    if not text or frequency <= 0:
        return text, False
    if len(text.split()) < 4:
        return text, False
    if turns_since_last < min_gap_turns:
        return text, False
    r = rng or random
    if r.random() >= frequency:
        return text, False
    return r.choice(_FILLERS) + text, True


# ---------------------------------------------------------------------------
# Response delay
# ---------------------------------------------------------------------------

def response_delay_ms(
    min_ms: int,
    max_ms: int,
    rng: random.Random | None = None,
) -> int:
    """Random delay in [min_ms, max_ms] inclusive. Clamped to non-negative."""
    if max_ms < min_ms:
        max_ms = min_ms
    if min_ms < 0:
        min_ms = 0
    r = rng or random
    return r.randint(min_ms, max_ms)


# ---------------------------------------------------------------------------
# Backchannel decision
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BackchannelDecision:
    play: bool
    sound: str        # one of _BACKCHANNELS or "" if play=False
    reason: str


_BACKCHANNELS = ("mm-hm", "right", "okay", "I see", "sure")


def should_backchannel(
    *,
    user_speech_duration_ms: float,
    last_backchannel_ms_ago: float,
    frequency: float,
    rng: random.Random | None = None,
) -> BackchannelDecision:
    """Decide whether to inject a low-priority backchannel sound.

    Heuristics:

    * Don't backchannel within the first 2 s — let the user get going.
    * Don't backchannel more than once per 4 s — gets annoying fast.
    * ``frequency`` gates the random fire (0..1, scaled per second of speech).
    """
    if frequency <= 0:
        return BackchannelDecision(False, "", "frequency_zero")
    if user_speech_duration_ms < 2_000:
        return BackchannelDecision(False, "", "too_early")
    if last_backchannel_ms_ago < 4_000:
        return BackchannelDecision(False, "", "cooldown")

    r = rng or random
    # Per-second probability so longer turns have a higher chance.
    per_sec = frequency
    p = 1.0 - (1.0 - per_sec) ** (user_speech_duration_ms / 1000.0)
    if r.random() >= p:
        return BackchannelDecision(False, "", "rng_no")

    return BackchannelDecision(True, r.choice(_BACKCHANNELS), "fired")


# ---------------------------------------------------------------------------
# Disclosure response
# ---------------------------------------------------------------------------

DEFAULT_DISCLOSURE = (
    "I'm an AI assistant calling on behalf of the team. "
    "I can answer questions, take requests, and connect you to a human if you'd like."
)
