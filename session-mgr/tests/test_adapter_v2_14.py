"""Tests for the v2.14 adapter — pure function checks, no HTTP."""

from __future__ import annotations

from uuid import uuid4

import pytest

from aipanel_vici.adapters.base import AdapterError
from aipanel_vici.adapters.v2_14 import ViciDialAdapter_2_14, base_url_from
from aipanel_vici.models import CapturedSession, DeploymentRow


@pytest.fixture()
def adapter() -> ViciDialAdapter_2_14:
    return ViciDialAdapter_2_14()


@pytest.fixture()
def deployment() -> DeploymentRow:
    return DeploymentRow(
        deployment_id=uuid4(),
        tenant_id=uuid4(),
        vici_server_id=uuid4(),
        web_url="https://vici.example.com/",
        asterisk_host="vici.example.com",
        vici_user="agent01",
        vici_pass="secret-vici-pass",
        phone_login="9001",
        phone_pass="phone-pass",
        campaign_id="SOLAR",
    )


@pytest.fixture()
def captured() -> CapturedSession:
    return CapturedSession(
        cookies={"PHPSESSID": "abc123"},
        conf_exten="8600051",
        session_id="VDADTOKENXYZ",
        session_name="agent01_2024",
    )


# ---------------------------------------------------------------------------
# base_url_from
# ---------------------------------------------------------------------------

def test_base_url_strips_path():
    assert base_url_from("https://vici.example.com/agc/") == "https://vici.example.com"
    assert base_url_from("http://10.0.0.5:8080/admin") == "http://10.0.0.5:8080"


def test_base_url_rejects_relative():
    with pytest.raises(ValueError):
        base_url_from("/agc/vicidial.php")


# ---------------------------------------------------------------------------
# Login form
# ---------------------------------------------------------------------------

def test_login_url(adapter, deployment):
    url = adapter.login_url("https://vici.example.com")
    assert url == "https://vici.example.com/agc/vicidial.php"


def test_login_form_fields_includes_credentials(adapter, deployment):
    fields = adapter.login_form_fields(deployment)
    assert fields["VD_login"] == "agent01"
    assert fields["VD_pass"] == "secret-vici-pass"
    assert fields["VD_campaign"] == "SOLAR"
    assert fields["phone_login"] == "9001"
    assert fields["relogin"] == "Y"


# ---------------------------------------------------------------------------
# parse_agent_page
# ---------------------------------------------------------------------------

_GOOD_AGENT_HTML = """
<html><body>
<script>
var conf_exten = '8600099';
var session_id = 'TOKENABCDEF';
var session_name = 'agent01_session';
</script>
</body></html>
"""

_LOGOUT_HTML = """
<html><body>NOT LOGGED-IN<br>Please login again.</body></html>
"""


def test_parse_agent_page_extracts_fields(adapter):
    out = adapter.parse_agent_page(_GOOD_AGENT_HTML, {"PHPSESSID": "x"})
    assert out.conf_exten == "8600099"
    assert out.session_id == "TOKENABCDEF"
    assert out.session_name == "agent01_session"
    assert out.cookies == {"PHPSESSID": "x"}


def test_parse_agent_page_rejects_logout_marker(adapter):
    with pytest.raises(AdapterError):
        adapter.parse_agent_page(_LOGOUT_HTML, {})


def test_parse_agent_page_missing_conf_exten(adapter):
    html = "<html>session_id = 'X'</html>"
    with pytest.raises(AdapterError, match="conf_exten"):
        adapter.parse_agent_page(html, {})


def test_parse_agent_page_missing_session_id(adapter):
    html = "<html>conf_exten = '999'</html>"
    with pytest.raises(AdapterError, match="session_id"):
        adapter.parse_agent_page(html, {})


# ---------------------------------------------------------------------------
# Heartbeat / session-expired detection
# ---------------------------------------------------------------------------

def test_heartbeat_request_uses_conf_exten(adapter, captured, deployment):
    spec = adapter.heartbeat_request(captured, deployment)
    assert spec.method == "GET"
    assert spec.path == "/agc/vdc_db_query.php"
    assert spec.params["function"] == "ConfExten_check"
    assert spec.params["conf_exten"] == "8600051"
    assert spec.params["user"] == "agent01"


def test_session_expired_on_401(adapter):
    assert adapter.is_response_session_expired("anything", 401) is True


def test_session_expired_on_logout_marker(adapter):
    assert adapter.is_response_session_expired("USER LOGGED OUT", 200) is True


def test_session_expired_on_empty_body(adapter):
    assert adapter.is_response_session_expired("", 200) is True


def test_session_not_expired_on_normal_response(adapter):
    assert adapter.is_response_session_expired("OK8600051", 200) is False


# ---------------------------------------------------------------------------
# Action requests
# ---------------------------------------------------------------------------

def test_dispose_request_includes_status(adapter, captured, deployment):
    spec = adapter.dispose_request(
        captured, deployment, "QUAL", None, "great chat",
    )
    assert spec.method == "POST"
    assert spec.path == "/agc/vdc_db_query.php"
    assert spec.data["function"] == "user_dispo_log"
    assert spec.data["status"] == "QUAL"
    assert spec.data["comments"] == "great chat"
    assert "callback" not in spec.data


def test_dispose_with_callback(adapter, captured, deployment):
    spec = adapter.dispose_request(
        captured, deployment, "CALLBK", "2026-05-08 14:00:00", "tomorrow at 2pm",
    )
    assert spec.data["callback"] == "Y"
    assert spec.data["callback_dt"] == "2026-05-08 14:00:00"


def test_transfer_request_targets_ingroup(adapter, captured, deployment):
    spec = adapter.transfer_conference_request(
        captured, deployment, "SALES", "hot lead, ready to buy",
    )
    assert spec.data["function"] == "transfer_park_call_to_x"
    assert spec.data["xfer_type"] == "IN_GROUP"
    assert spec.data["ingroup"] == "SALES"
    assert "hot lead" in spec.data["comments"]


def test_pause_resume_pair(adapter, captured, deployment):
    p = adapter.pause_request(captured, deployment, "BIO")
    r = adapter.resume_request(captured, deployment)
    assert p.data["stage"] == "PAUSED"
    assert p.data["pause_code"] == "BIO"
    assert r.data["stage"] == "READY"


def test_hangup_request(adapter, captured, deployment):
    spec = adapter.hangup_request(captured, deployment)
    assert spec.data["call_action"] == "HANGUP_CUSTOMER"


# ---------------------------------------------------------------------------
# Lead parsing
# ---------------------------------------------------------------------------

def test_parse_lead_response_handles_tabs(adapter):
    parts = [""] * 25
    parts[0] = "12345"
    parts[8] = "14155551234"
    parts[10] = "Pat"
    parts[12] = "Doe"
    parts[16] = "San Francisco"
    parts[17] = "CA"
    parts[19] = "94110"
    parts[24] = "pat@example.com"
    body = "\t".join(parts)
    lead = adapter.parse_lead_response(body, "12345")
    assert lead.lead_id == "12345"
    assert lead.first_name == "Pat"
    assert lead.last_name == "Doe"
    assert lead.phone_number == "14155551234"
    assert lead.email == "pat@example.com"
    assert lead.city == "San Francisco"


def test_parse_lead_response_empty_body(adapter):
    lead = adapter.parse_lead_response("", "999")
    assert lead.lead_id == "999"
    assert lead.first_name == ""


# ---------------------------------------------------------------------------
# Call info parsing
# ---------------------------------------------------------------------------

def test_parse_call_info_extracts_lead_id(adapter):
    # 16 fields, lead_id at index 11, uniqueid at 12, phone at 15.
    fields = ["READY"] + [""] * 11 + ["L42", "1700000000.5", "SOLAR", "L1", "+18005551234"]
    body = "|".join(fields)
    info = adapter.parse_call_info_response(body)
    assert info.lead_id == "L42"
    assert info.uniqueid == "1700000000.5"
    assert info.phone_number == "+18005551234"


def test_parse_call_info_empty(adapter):
    assert adapter.parse_call_info_response("") == adapter.parse_call_info_response("")
