"""Tests for barge_in.should_barge_in — pure decision function."""

from __future__ import annotations

from aipanel_worker.barge_in import should_barge_in


def test_no_barge_in_when_agent_silent():
    d = should_barge_in(
        partial_text="hello there how are you",
        partial_stability=0.9,
        partial_duration_ms=2000,
        is_speaking=False,
    )
    assert d.cancel_tts is False
    assert d.reason == "agent_silent"


def test_no_barge_in_for_empty_partial():
    d = should_barge_in(
        partial_text="",
        partial_stability=1.0,
        partial_duration_ms=1500,
        is_speaking=True,
    )
    assert d.cancel_tts is False
    assert d.reason == "empty_partial"


def test_no_barge_in_for_low_stability():
    d = should_barge_in(
        partial_text="hello there how are you",
        partial_stability=0.3,
        partial_duration_ms=1500,
        is_speaking=True,
        stability_threshold=0.6,
    )
    assert d.cancel_tts is False
    assert d.reason == "low_stability"


def test_no_barge_in_for_short_backchannel():
    # "uh huh" — 2 words, 500 ms. Both gates fail → filtered.
    d = should_barge_in(
        partial_text="uh huh",
        partial_stability=0.9,
        partial_duration_ms=500,
        is_speaking=True,
        min_words=3,
        min_duration_ms=800,
    )
    assert d.cancel_tts is False
    assert d.reason == "backchannel_filtered"


def test_barge_in_on_real_interruption_word_count_satisfied():
    d = should_barge_in(
        partial_text="hold on please let me think",
        partial_stability=0.9,
        partial_duration_ms=300,         # short BUT enough words
        is_speaking=True,
        min_words=3,
        min_duration_ms=800,
    )
    assert d.cancel_tts is True
    assert d.reason == "user_interrupting"


def test_barge_in_on_real_interruption_duration_satisfied():
    d = should_barge_in(
        partial_text="no really",          # only 2 words — but long
        partial_stability=0.9,
        partial_duration_ms=1500,
        is_speaking=True,
        min_words=3,
        min_duration_ms=800,
    )
    assert d.cancel_tts is True


def test_barge_in_with_default_thresholds():
    d = should_barge_in(
        partial_text="actually I changed my mind",
        partial_stability=0.7,
        partial_duration_ms=1200,
        is_speaking=True,
    )
    assert d.cancel_tts is True
