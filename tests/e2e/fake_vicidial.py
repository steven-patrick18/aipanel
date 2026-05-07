"""Minimal in-process FastAPI app that emulates the bits of ViciDial the
session-manager talks to.

Does NOT cover Asterisk / RTP / actual call routing. The goal is to let
us assert that, given a scripted vici behaviour (login OK, then heartbeat
OK, then a deal-closing dispo), the session-mgr + worker pipeline behaves
correctly — without a real ViciDial install in the test environment.

Endpoints emulated (matching the v2.14 adapter):
- POST /agc/vicidial.php          → returns the agent UI HTML on first
                                    call, then the heartbeat-friendly OK
                                    on subsequent calls
- GET  /agc/vdc_db_query.php      → switches on ``function=`` param:
                                    ConfExten_check / user_status /
                                    user_dispo_log / transfer_park_call_to_x /
                                    pause_session_log / ra_call_control
- GET  /vicidial/non_agent_api.php → update_lead query
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse


_AGENT_PAGE_TEMPLATE = """<!doctype html>
<html><head><title>aipanel-fake-vici</title></head>
<body>
<script>
var conf_exten   = '{conf_exten}';
var session_id   = '{session_id}';
var session_name = '{session_name}';
</script>
<p>fake-vici agent UI</p>
</body></html>
"""


@dataclass
class FakeViciState:
    """Records what the session-mgr did. Tests assert against these."""
    logins: list[dict[str, Any]] = field(default_factory=list)
    heartbeats: int = 0
    actions: list[dict[str, Any]] = field(default_factory=list)
    expire_session_after: int = 0     # 0 = never. >0 = nth heartbeat returns "logged out"
    next_dispo: str | None = None


def make_fake_vici_app(state: FakeViciState | None = None) -> tuple[FastAPI, FakeViciState]:
    state = state or FakeViciState()
    app = FastAPI()

    # ---- Login + heartbeat surface ----
    @app.post("/agc/vicidial.php")
    async def vicidial_post(
        VD_login:    str = Form(""),
        VD_pass:     str = Form(""),
        VD_campaign: str = Form(""),
        phone_login: str = Form(""),
        phone_pass:  str = Form(""),
        relogin:     str = Form(""),
        logout:      str = Form(""),
        DB:          str = Form(""),
    ) -> HTMLResponse:
        if logout == "LOGOUT":
            state.actions.append({"kind": "logout", "user": VD_login})
            return HTMLResponse("<html>Logged out</html>")
        state.logins.append({
            "user": VD_login, "campaign": VD_campaign,
            "phone_login": phone_login, "relogin": relogin,
        })
        return HTMLResponse(_AGENT_PAGE_TEMPLATE.format(
            conf_exten=8600100 + len(state.logins),
            session_id="FAKETOKEN" + str(len(state.logins)),
            session_name=f"{VD_login}_session",
        ))

    @app.get("/agc/vicidial.php")
    async def vicidial_get() -> HTMLResponse:
        # Some installs also serve the page on GET. Return the same shape.
        return HTMLResponse(_AGENT_PAGE_TEMPLATE.format(
            conf_exten=8600100, session_id="FAKETOKEN0",
            session_name="reload",
        ))

    # ---- AJAX surface ----
    @app.get("/agc/vdc_db_query.php")
    async def vdc_db_query_get(request: Request) -> PlainTextResponse:
        params = dict(request.query_params)
        fn = params.get("function", "")

        if fn == "ConfExten_check":
            state.heartbeats += 1
            if (state.expire_session_after
                    and state.heartbeats >= state.expire_session_after):
                return PlainTextResponse("NOT LOGGED-IN")
            return PlainTextResponse(f"OK{params.get('conf_exten', '')}")

        if fn == "user_status":
            # 16 fields, 11=lead_id, 12=uniqueid, 15=phone.
            if state.next_dispo == "ON_CALL":
                fields = (
                    ["INCALL"] + [""] * 10
                    + ["L42", "1700000000.5", "FAKE", "L1", "+18005551234"]
                )
                return PlainTextResponse("|".join(fields))
            return PlainTextResponse("READY|" + "|" * 14)

        return PlainTextResponse("OK")

    @app.post("/agc/vdc_db_query.php")
    async def vdc_db_query_post(request: Request) -> PlainTextResponse:
        form = await request.form()
        fn = form.get("function", "")
        record: dict[str, Any] = {"kind": fn, **{k: form.get(k) for k in form.keys()}}
        state.actions.append(record)
        return PlainTextResponse("OK")

    @app.get("/vicidial/non_agent_api.php")
    async def non_agent_api(request: Request) -> PlainTextResponse:
        params = dict(request.query_params)
        if params.get("function") == "update_lead" and params.get("query") == "Y":
            # Tab-separated row matching our adapter's parse_lead_response.
            parts = [""] * 25
            parts[0] = params.get("lead_id", "")
            parts[8] = "+18005551234"
            parts[10] = "Test"
            parts[12] = "Lead"
            parts[16] = "San Francisco"
            parts[17] = "CA"
            parts[19] = "94110"
            parts[24] = "test@example.com"
            return PlainTextResponse("\t".join(parts))
        return PlainTextResponse("")

    return app, state
