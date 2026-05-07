"""Tests for aipanel_sip.header_parser."""

from __future__ import annotations

import pytest

from aipanel_sip.header_parser import parse_headers


SAMPLE_INVITE = (
    "INVITE sip:1001@aipanel.local SIP/2.0\r\n"
    "Via: SIP/2.0/UDP 10.0.0.5:5060;branch=z9hG4bK-abc\r\n"
    "Max-Forwards: 70\r\n"
    "From: \"Vicidial\" <sip:vici@10.0.0.5>;tag=12345\r\n"
    "To: <sip:1001@aipanel.local>\r\n"
    "Call-ID: 5f4a3b2c-1234@10.0.0.5\r\n"
    "CSeq: 1 INVITE\r\n"
    "Contact: <sip:vici@10.0.0.5:5060>\r\n"
    "X-Vicidial-LeadId: 987654\r\n"
    "X-Vicidial-Uniqueid: 1700000000.42\r\n"
    "X-Vicidial-Campaign: SOLAR\r\n"
    "X-Vicidial-Phone: 14155551234\r\n"
    "P-Asserted-Identity: <sip:14155551234@vici.example.com>\r\n"
    "Content-Type: application/sdp\r\n"
    "Content-Length: 0\r\n"
    "\r\n"
)


def test_parses_all_known_headers():
    h = parse_headers(SAMPLE_INVITE)
    assert h["vici_lead_id"]        == "987654"
    assert h["vici_uniqueid"]       == "1700000000.42"
    assert h["vici_campaign"]       == "SOLAR"
    assert h["vici_phone"]          == "14155551234"
    assert h["p_asserted_identity"] == "<sip:14155551234@vici.example.com>"


def test_returns_empty_for_empty_input():
    assert parse_headers("") == {}
    assert parse_headers(None) == {}  # type: ignore[arg-type]


def test_ignores_unknown_headers():
    msg = (
        "INVITE sip:x@host SIP/2.0\r\n"
        "X-Other-Vendor: some-value\r\n"
        "Content-Length: 0\r\n"
        "\r\n"
    )
    assert parse_headers(msg) == {}


def test_case_insensitive_header_names():
    msg = (
        "INVITE sip:x@host SIP/2.0\r\n"
        "x-vicidial-leadid: 42\r\n"
        "X-VICIDIAL-PHONE: 18005551234\r\n"
        "\r\n"
    )
    h = parse_headers(msg)
    assert h["vici_lead_id"] == "42"
    assert h["vici_phone"]   == "18005551234"


def test_handles_lf_only_endings():
    # Some test fixtures (and some buggy clients) use LF instead of CRLF.
    msg = (
        "INVITE sip:x@host SIP/2.0\n"
        "X-Vicidial-LeadId: 1\n"
        "\n"
    )
    assert parse_headers(msg) == {"vici_lead_id": "1"}


def test_handles_continuation_lines():
    msg = (
        "INVITE sip:x@host SIP/2.0\r\n"
        "P-Asserted-Identity: <sip:14155551234@vici.example.com>\r\n"
        "  ;tag=continuation\r\n"
        "\r\n"
    )
    h = parse_headers(msg)
    assert h["p_asserted_identity"] == \
        "<sip:14155551234@vici.example.com> ;tag=continuation"


def test_stops_at_body_separator():
    # Anything after the blank line is the SDP body and must be ignored,
    # even if it contains text that looks like headers.
    msg = (
        "INVITE sip:x@host SIP/2.0\r\n"
        "X-Vicidial-LeadId: real\r\n"
        "\r\n"
        "X-Vicidial-LeadId: from-the-body\r\n"
    )
    assert parse_headers(msg) == {"vici_lead_id": "real"}


def test_malformed_header_does_not_break_parser():
    msg = (
        "INVITE sip:x@host SIP/2.0\r\n"
        "this-line-has-no-colon\r\n"
        "X-Vicidial-LeadId: still-parsed\r\n"
        "\r\n"
    )
    assert parse_headers(msg) == {"vici_lead_id": "still-parsed"}
