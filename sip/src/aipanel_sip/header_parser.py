"""Parse aipanel-relevant headers out of a raw SIP INVITE.

pjsua2 surfaces incoming headers as the raw on-wire message text via
``OnIncomingCallParam.rdata.wholeMsg``. We do a small, defensive RFC-3261
header parse rather than pulling in a full SIP grammar — we only care about
five named headers, all single-line.
"""

from __future__ import annotations

# Lowercased for case-insensitive comparison, mapped to the canonical name
# used in CallContext.
_HEADER_MAP: dict[str, str] = {
    "x-vicidial-leadid":      "vici_lead_id",
    "x-vicidial-uniqueid":    "vici_uniqueid",
    "x-vicidial-campaign":    "vici_campaign",
    "x-vicidial-phone":       "vici_phone",
    "p-asserted-identity":    "p_asserted_identity",
}


def parse_headers(raw_msg: str) -> dict[str, str]:
    """Extract aipanel-relevant headers from a raw SIP message.

    Returns a dict keyed by the canonical CallContext field name
    (e.g. ``"vici_lead_id"``). Headers not present in the message are
    omitted; the caller should treat missing keys as ``None``.

    The parser stops at the first blank line (end of headers per RFC 3261).
    Continuation lines (RFC 3261 §7.3.1) are folded; multi-value repeats of
    the same header keep the last occurrence.
    """
    if not raw_msg:
        return {}

    out: dict[str, str] = {}
    pending_name: str | None = None
    pending_value: str = ""

    def _flush() -> None:
        nonlocal pending_name, pending_value
        if pending_name is None:
            return
        canonical = _HEADER_MAP.get(pending_name.lower())
        if canonical is not None:
            out[canonical] = pending_value.strip()
        pending_name = None
        pending_value = ""

    # Split on CRLF or LF; SIP wire uses CRLF but tests are kinder with LF.
    for raw_line in raw_msg.replace("\r\n", "\n").split("\n"):
        # Skip the request/status line and stop at the body separator.
        if not raw_line:
            _flush()
            break
        if raw_line.startswith(("INVITE ", "SIP/2.0 ", "ACK ", "BYE ", "CANCEL ", "OPTIONS ")):
            continue

        # Continuation line (RFC 3261 §7.3.1): leading whitespace folds
        # into the previous header value.
        if raw_line[0] in (" ", "\t"):
            if pending_name is not None:
                pending_value += " " + raw_line.strip()
            continue

        _flush()

        if ":" not in raw_line:
            # Malformed header line — ignore and keep parsing.
            continue
        name, _, value = raw_line.partition(":")
        pending_name = name.strip()
        pending_value = value

    _flush()
    return out
