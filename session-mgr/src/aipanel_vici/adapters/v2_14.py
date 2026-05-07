"""ViciDial 2.14 adapter.

Endpoint shapes
---------------

Everything in this file is based on standard-distribution ViciDial 2.14 as
documented at vicidial.org and as visible in the open-source agent UI's
``vicidial.php`` + ``vdc_db_query.php`` AJAX traffic. Customer forks
frequently rename functions or add custom params; **every endpoint here
should be validated against the customer's actual install** before going
into production.

Markers we look for in HTML responses:
* ``"Logged out"`` / ``"NOT LOGGED-IN"`` → session expired
* ``conf_exten=NNNN`` JS variable → captured during login
* ``session_id=NNNNN`` JS variable → captured during login

vdc_db_query.php functions used (function= param):
* ``ConfExten_check``        — heartbeat poll
* ``user_status``            — agent status (READY/PAUSED/INCALL/...)
* ``ra_call_control``        — call control (hangup, transfer, etc.)
* ``user_dispo_log``         — disposition write
* ``transfer_park_call_to_x``— conference transfer
* ``pause_session_log``      — pause/resume

For lead data we hit ``vdc_db_query.php?function=user_status_change`` with
the appropriate flags or fall back to ``api.php?source=...&function=update_lead``.
The exact lead-fetch endpoint is the single biggest fragility point — the
customer-specific vicidial install often patches this. We use
``non_agent_api.php?function=update_lead&query=Y`` which returns a tab-
separated record per the documented API.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from ..models import CallInfo, CapturedSession, DeploymentRow, LeadData
from .base import AdapterError, HttpRequestSpec, VicidialAdapter

# ---------------------------------------------------------------------------
# HTML / response markers
# ---------------------------------------------------------------------------

_LOGOUT_MARKERS = (
    "NOT LOGGED-IN",
    "logout_session",
    "USER LOGGED OUT",
    "session_expired",
)

_RE_CONF_EXTEN = re.compile(r"conf_exten\s*=\s*['\"]?(\d+)", re.IGNORECASE)
_RE_SESSION_ID = re.compile(r"session_id\s*=\s*['\"]?([A-Za-z0-9]+)", re.IGNORECASE)
_RE_SESSION_NAME = re.compile(r"session_name\s*=\s*['\"]?([A-Za-z0-9_\-]+)",
                              re.IGNORECASE)


class ViciDialAdapter_2_14(VicidialAdapter):
    name = "v2_14"

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    def login_url(self, base_url: str) -> str:
        # Standard agent entry point. The form on this page POSTs back to
        # itself with the credentials.
        return f"{base_url.rstrip('/')}/agc/vicidial.php"

    def login_form_fields(self, deployment: DeploymentRow) -> dict[str, str]:
        # ViciDial agent login fields. ``relogin=Y`` forces a fresh session
        # and discards any stale entry in vicidial_users_cache.
        return {
            "VD_login":     deployment.vici_user,
            "VD_pass":      deployment.vici_pass,
            "VD_campaign":  deployment.campaign_id,
            "phone_login":  deployment.phone_login,
            "phone_pass":   deployment.phone_pass,
            "relogin":      "Y",
            # Older 2.14 forms include this hidden field; harmless if extra.
            "DB":           "0",
        }

    def parse_agent_page(self, html: str, cookies: dict[str, str]) -> CapturedSession:
        if not html:
            raise AdapterError("agent page response was empty")
        if any(m in html for m in _LOGOUT_MARKERS):
            raise AdapterError("agent page contains logout markers — login likely failed")

        m_exten = _RE_CONF_EXTEN.search(html)
        m_sid = _RE_SESSION_ID.search(html)
        if not m_exten:
            raise AdapterError("could not extract conf_exten from agent page")
        if not m_sid:
            raise AdapterError("could not extract session_id from agent page")

        m_name = _RE_SESSION_NAME.search(html)

        return CapturedSession(
            cookies=cookies,
            conf_exten=m_exten.group(1),
            session_id=m_sid.group(1),
            session_name=m_name.group(1) if m_name else "",
        )

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def heartbeat_request(self, sess: CapturedSession,
                          deployment: DeploymentRow) -> HttpRequestSpec:
        # ConfExten_check is the lightest call ViciDial's agent UI makes on
        # the heartbeat timer (~every 1.5 s). It returns "OK<conf_exten>"
        # or an empty body when the session has gone away.
        return HttpRequestSpec(
            method="GET",
            path="/agc/vdc_db_query.php",
            params={
                "function": "ConfExten_check",
                "user": deployment.vici_user,
                "pass": deployment.vici_pass,
                "conf_exten": sess.conf_exten,
                "session_name": sess.session_name,
                "stage": "heartbeat",
            },
        )

    def is_response_session_expired(self, body: str, status_code: int) -> bool:
        if status_code in (401, 403):
            return True
        if not body:
            # Empty body from an AJAX endpoint usually means the session row
            # was wiped from vicidial_users_cache.
            return True
        return any(m in body for m in _LOGOUT_MARKERS)

    # ------------------------------------------------------------------
    # Call info
    # ------------------------------------------------------------------

    def get_call_info_request(self, sess: CapturedSession,
                              deployment: DeploymentRow) -> HttpRequestSpec:
        return HttpRequestSpec(
            method="GET",
            path="/agc/vdc_db_query.php",
            params={
                "function": "user_status",
                "user": deployment.vici_user,
                "pass": deployment.vici_pass,
                "session_name": sess.session_name,
                "format": "vars",
            },
        )

    def parse_call_info_response(self, body: str) -> CallInfo:
        # The ``user_status`` response (format=vars) returns a pipe-separated
        # record. Field positions per ViciDial 2.14 source:
        #   status|server_ip|conf_exten|extension|...|lead_id|uniqueid|
        #   campaign|list_id|phone_number|...
        # Mapping below is best-effort; some forks reorder.
        if not body or not body.strip():
            return CallInfo()
        fields = body.strip().split("|")
        # Lookup helper that tolerates missing fields.
        def at(i: int) -> str | None:
            return fields[i] if i < len(fields) and fields[i] else None
        return CallInfo(
            lead_id=at(11),
            uniqueid=at(12),
            campaign_id=at(13),
            list_id=at(14),
            phone_number=at(15),
        )

    # ------------------------------------------------------------------
    # Lead data
    # ------------------------------------------------------------------

    def get_lead_request(self, sess: CapturedSession,
                         deployment: DeploymentRow,
                         lead_id: str) -> HttpRequestSpec:
        # vicidial_non_agent_api accepts admin credentials, not agent ones.
        # The session_worker swaps in vicidial_servers.web_user_admin before
        # sending — we just construct the request shape here.
        return HttpRequestSpec(
            method="GET",
            path="/vicidial/non_agent_api.php",
            params={
                "source":   "aipanel",
                "function": "update_lead",
                "query":    "Y",
                "lead_id":  lead_id,
            },
        )

    def parse_lead_response(self, body: str, lead_id: str) -> LeadData:
        if not body:
            return LeadData(lead_id=lead_id)
        # update_lead query response is tab-separated. Field order from the
        # ViciDial admin manual:
        #   lead_id\tentry_date\t...\tphone_number\ttitle\tfirst_name\tmiddle_initial\t
        #   last_name\taddress1\taddress2\taddress3\tcity\tstate\tprovince\t
        #   postal_code\tcountry_code\tgender\tdate_of_birth\talt_phone\temail\t
        #   security_phrase\tcomments
        parts = body.strip().split("\t")
        def at(i: int) -> str:
            return parts[i] if i < len(parts) else ""
        return LeadData(
            lead_id=at(0) or lead_id,
            phone_number=at(8),
            first_name=at(10),
            last_name=at(12),
            address=" ".join(p for p in (at(13), at(14), at(15)) if p),
            city=at(16),
            state=at(17),
            postal_code=at(19),
            email=at(24),
        )

    # ------------------------------------------------------------------
    # Disposition
    # ------------------------------------------------------------------

    def dispose_request(self, sess: CapturedSession,
                        deployment: DeploymentRow,
                        status: str,
                        callback_datetime: str | None,
                        notes: str) -> HttpRequestSpec:
        params: dict[str, Any] = {
            "function":     "user_dispo_log",
            "user":         deployment.vici_user,
            "pass":         deployment.vici_pass,
            "campaign":     deployment.campaign_id,
            "session_name": sess.session_name,
            "status":       status,
            "comments":     notes or "",
        }
        if callback_datetime:
            params["callback"]      = "Y"
            params["callback_dt"]   = callback_datetime
            params["callback_type"] = "USERONLY"
        return HttpRequestSpec(
            method="POST",
            path="/agc/vdc_db_query.php",
            data=params,
        )

    # ------------------------------------------------------------------
    # Transfer (conference drop to in-group)
    # ------------------------------------------------------------------

    def transfer_conference_request(self, sess: CapturedSession,
                                    deployment: DeploymentRow,
                                    ingroup_id: str,
                                    summary: str) -> HttpRequestSpec:
        # transfer_park_call_to_x with xfer_type=IN_GROUP places the customer
        # leg into the named in-group queue, then drops our agent leg.
        return HttpRequestSpec(
            method="POST",
            path="/agc/vdc_db_query.php",
            data={
                "function":     "transfer_park_call_to_x",
                "user":         deployment.vici_user,
                "pass":         deployment.vici_pass,
                "session_name": sess.session_name,
                "conf_exten":   sess.conf_exten,
                "xfer_type":    "IN_GROUP",
                "ingroup":      ingroup_id,
                "comments":     summary[:1000],   # ViciDial truncates at 1k anyway
                "leave_3way":   "0",              # we drop, no 3-way hold
            },
        )

    # ------------------------------------------------------------------
    # Pause / resume
    # ------------------------------------------------------------------

    def pause_request(self, sess: CapturedSession,
                      deployment: DeploymentRow,
                      pause_code: str) -> HttpRequestSpec:
        return HttpRequestSpec(
            method="POST",
            path="/agc/vdc_db_query.php",
            data={
                "function":     "pause_session_log",
                "user":         deployment.vici_user,
                "pass":         deployment.vici_pass,
                "campaign":     deployment.campaign_id,
                "session_name": sess.session_name,
                "stage":        "PAUSED",
                "pause_code":   pause_code,
            },
        )

    def resume_request(self, sess: CapturedSession,
                       deployment: DeploymentRow) -> HttpRequestSpec:
        return HttpRequestSpec(
            method="POST",
            path="/agc/vdc_db_query.php",
            data={
                "function":     "pause_session_log",
                "user":         deployment.vici_user,
                "pass":         deployment.vici_pass,
                "campaign":     deployment.campaign_id,
                "session_name": sess.session_name,
                "stage":        "READY",
            },
        )

    # ------------------------------------------------------------------
    # Hangup (current call only, no transfer)
    # ------------------------------------------------------------------

    def hangup_request(self, sess: CapturedSession,
                       deployment: DeploymentRow) -> HttpRequestSpec:
        return HttpRequestSpec(
            method="POST",
            path="/agc/vdc_db_query.php",
            data={
                "function":     "ra_call_control",
                "user":         deployment.vici_user,
                "pass":         deployment.vici_pass,
                "session_name": sess.session_name,
                "conf_exten":   sess.conf_exten,
                "call_action":  "HANGUP_CUSTOMER",
            },
        )

    # ------------------------------------------------------------------
    # Logout
    # ------------------------------------------------------------------

    def logout_request(self, sess: CapturedSession,
                       deployment: DeploymentRow) -> HttpRequestSpec:
        return HttpRequestSpec(
            method="POST",
            path="/agc/vicidial.php",
            data={
                "DB":           "0",
                "VD_login":     deployment.vici_user,
                "VD_pass":      deployment.vici_pass,
                "logout":       "LOGOUT",
                "session_name": sess.session_name,
            },
        )

    # ------------------------------------------------------------------
    # Manual dial — used by /test-call from the panel
    # ------------------------------------------------------------------

    def manual_dial_request(self, sess: CapturedSession,
                            deployment: DeploymentRow,
                            phone_number: str) -> HttpRequestSpec:
        # ext_manual_dial originates an outbound call from this agent's
        # extension. ViciDial bridges the answered customer leg back into
        # our SIP layer, where it appears as a normal inbound INVITE — the
        # worker then handles it like any other call.
        return HttpRequestSpec(
            method="POST",
            path="/agc/vdc_db_query.php",
            data={
                "function":     "ext_manual_dial",
                "user":         deployment.vici_user,
                "pass":         deployment.vici_pass,
                "session_name": sess.session_name,
                "phone_number": phone_number,
                "phone_code":   "1",
                "campaign":     deployment.campaign_id,
                "search":       "NO",
                "preview":      "NO",
                "focus":        "YES",
            },
        )


# ---------------------------------------------------------------------------
# Misc helpers — consumed by login.py for pre-flight URL sanity checks.
# ---------------------------------------------------------------------------

def base_url_from(web_url: str) -> str:
    """Strip any path component to produce a base URL like ``https://vici.example.com``."""
    parts = urlsplit(web_url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"web_url is not a fully qualified URL: {web_url!r}")
    return f"{parts.scheme}://{parts.netloc}"
