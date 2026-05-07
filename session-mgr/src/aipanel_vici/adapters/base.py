"""Abstract adapter interface for talking to ViciDial.

An adapter encapsulates everything that's likely to change between ViciDial
versions / customer forks:

* Login form field names and submit URL
* Agent-page HTML markers we extract ``conf_exten`` / ``session_id`` from
* AJAX endpoint paths (``vdc_db_query.php``, ``api.php``, etc.)
* Function names + parameter shapes for each action
* Response parsing (success markers, error patterns)

The orchestrator (``session_worker``) only talks to the adapter via this
interface, so adding ViciDial 2.16 support means adding ``v2_16.py`` with
overridden methods rather than touching the worker.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any

from ..models import CallInfo, CapturedSession, DeploymentRow, LeadData


@dataclass
class HttpRequestSpec:
    """A description of an HTTP request the adapter wants to send.

    The session worker turns this into a real ``httpx`` call using the
    captured session cookies. Keeping the adapter pure (no httpx import)
    makes it trivially unit-testable.
    """
    method: str                          # "GET" | "POST"
    path: str                            # path relative to base_url
    params: dict[str, Any] | None = None
    data: dict[str, Any] | None = None   # form-encoded
    json: dict[str, Any] | None = None   # JSON body
    expect_html: bool = False
    """If True, response is expected to be HTML (agent UI). If False, the
    response is expected to be a small text/JSON blob from an AJAX endpoint.
    """


class AdapterError(Exception):
    """Raised when the adapter cannot complete a parse / build step."""


class SessionExpired(AdapterError):
    """The response indicates our session is no longer valid (re-login needed)."""


class VicidialAdapter(abc.ABC):
    """Subclass per supported ViciDial version."""

    name: str = "base"

    # ------------------------------------------------------------------
    # Login (consumed by login.py via Playwright)
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def login_url(self, base_url: str) -> str:
        """Absolute URL Playwright navigates to to render the login form."""

    @abc.abstractmethod
    def login_form_fields(self, deployment: DeploymentRow) -> dict[str, str]:
        """Map of ``<input name>`` → value for the login form."""

    @abc.abstractmethod
    def parse_agent_page(self, html: str, cookies: dict[str, str]) -> CapturedSession:
        """Extract ``conf_exten`` / ``session_id`` from the rendered agent page.

        Raises AdapterError if the page doesn't look like a logged-in agent UI.
        """

    # ------------------------------------------------------------------
    # AJAX actions (consumed by session_worker, sent via httpx)
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def heartbeat_request(self, sess: CapturedSession,
                          deployment: DeploymentRow) -> HttpRequestSpec:
        ...

    @abc.abstractmethod
    def is_response_session_expired(self, body: str, status_code: int) -> bool:
        """Detect ViciDial's "you are logged out" markers in any response body."""

    @abc.abstractmethod
    def get_call_info_request(self, sess: CapturedSession,
                              deployment: DeploymentRow) -> HttpRequestSpec:
        ...

    @abc.abstractmethod
    def parse_call_info_response(self, body: str) -> CallInfo:
        ...

    @abc.abstractmethod
    def get_lead_request(self, sess: CapturedSession,
                         deployment: DeploymentRow,
                         lead_id: str) -> HttpRequestSpec:
        ...

    @abc.abstractmethod
    def parse_lead_response(self, body: str, lead_id: str) -> LeadData:
        ...

    @abc.abstractmethod
    def dispose_request(self, sess: CapturedSession,
                        deployment: DeploymentRow,
                        status: str,
                        callback_datetime: str | None,
                        notes: str) -> HttpRequestSpec:
        ...

    @abc.abstractmethod
    def transfer_conference_request(self, sess: CapturedSession,
                                    deployment: DeploymentRow,
                                    ingroup_id: str,
                                    summary: str) -> HttpRequestSpec:
        ...

    @abc.abstractmethod
    def pause_request(self, sess: CapturedSession,
                      deployment: DeploymentRow,
                      pause_code: str) -> HttpRequestSpec:
        ...

    @abc.abstractmethod
    def resume_request(self, sess: CapturedSession,
                       deployment: DeploymentRow) -> HttpRequestSpec:
        ...

    @abc.abstractmethod
    def hangup_request(self, sess: CapturedSession,
                       deployment: DeploymentRow) -> HttpRequestSpec:
        ...

    @abc.abstractmethod
    def logout_request(self, sess: CapturedSession,
                       deployment: DeploymentRow) -> HttpRequestSpec:
        ...

    # ------------------------------------------------------------------
    # Operator-initiated outbound dial — used by /test-call from the panel
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def manual_dial_request(self, sess: CapturedSession,
                            deployment: DeploymentRow,
                            phone_number: str) -> HttpRequestSpec:
        """Originate an outbound call to ``phone_number`` from this agent
        seat. ViciDial bridges the leg into our SIP extension just like
        an inbound dialler call, so the worker takes over once it arrives."""
