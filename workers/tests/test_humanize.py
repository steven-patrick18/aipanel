"""Tests for aipanel_worker.humanize — all pure functions, all deterministic."""

from __future__ import annotations

import random

import pytest

from aipanel_worker.humanize import (
    BackchannelDecision,
    inject_filler,
    pick_opener,
    response_delay_ms,
    should_backchannel,
)


# ---------------------------------------------------------------------------
# pick_opener
# ---------------------------------------------------------------------------

def test_pick_opener_empty_returns_empty():
    assert pick_opener([]) == ""


def test_pick_opener_single():
    assert pick_opener(["hi there"]) == "hi there"


def test_pick_opener_seeded_is_deterministic():
    rng = random.Random(0)
    assert pick_opener(["a", "b", "c", "d"], rng=rng) in {"a", "b", "c", "d"}


# ---------------------------------------------------------------------------
# inject_filler
# ---------------------------------------------------------------------------

def test_inject_filler_zero_frequency_never_injects():
    text, did = inject_filler("hello there friend",
                              frequency=0.0, turns_since_last=10)
    assert text == "hello there friend"
    assert did is False


def test_inject_filler_too_short_never_injects():
    text, did = inject_filler("yes", frequency=1.0, turns_since_last=10)
    assert text == "yes"
    assert did is False


def test_inject_filler_recent_filler_blocks():
    text, did = inject_filler(
        "hello there friend, how are you doing today",
        frequency=1.0,
        turns_since_last=1,
        min_gap_turns=4,
    )
    assert did is False
    assert text == "hello there friend, how are you doing today"


def test_inject_filler_at_full_frequency_after_gap():
    rng = random.Random(0)
    text, did = inject_filler(
        "hello there friend, how are you doing today",
        frequency=1.0,
        turns_since_last=99,
        min_gap_turns=4,
        rng=rng,
    )
    assert did is True
    assert text.endswith("hello there friend, how are you doing today")
    assert text != "hello there friend, how are you doing today"


# ---------------------------------------------------------------------------
# response_delay_ms
# ---------------------------------------------------------------------------

def test_response_delay_within_range():
    rng = random.Random(0)
    for _ in range(50):
        d = response_delay_ms(300, 900, rng=rng)
        assert 300 <= d <= 900


def test_response_delay_handles_inverted_range():
    # If max < min we clamp max up to min instead of crashing.
    d = response_delay_ms(900, 300, rng=random.Random(0))
    assert d == 900


def test_response_delay_floors_negative():
    d = response_delay_ms(-100, 50, rng=random.Random(0))
    assert 0 <= d <= 50


# ---------------------------------------------------------------------------
# should_backchannel
# ---------------------------------------------------------------------------

def test_backchannel_too_early_skipped():
    d = should_backchannel(
        user_speech_duration_ms=1500,
        last_backchannel_ms_ago=10_000,
        frequency=1.0,
        rng=random.Random(0),
    )
    assert d.play is False
    assert d.reason == "too_early"


def test_backchannel_cooldown_respected():
    d = should_backchannel(
        user_speech_duration_ms=5000,
        last_backchannel_ms_ago=2000,
        frequency=1.0,
        rng=random.Random(0),
    )
    assert d.play is False
    assert d.reason == "cooldown"


def test_backchannel_zero_frequency_never_plays():
    d = should_backchannel(
        user_speech_duration_ms=10_000,
        last_backchannel_ms_ago=10_000,
        frequency=0.0,
        rng=random.Random(0),
    )
    assert d.play is False
    assert d.reason == "frequency_zero"


def test_backchannel_high_frequency_long_speech_can_fire():
    # Frequency 0.99 over 10 s of speech makes p ≈ 1.0 — even seed 0 fires.
    d = should_backchannel(
        user_speech_duration_ms=10_000,
        last_backchannel_ms_ago=10_000,
        frequency=0.99,
        rng=random.Random(0),
    )
    assert d.play is True
    assert d.sound != ""
    assert isinstance(d, BackchannelDecision)
