"""Shared data models for the Session Manager.

`SessionState` is the per-deployment in-memory record (mirrored to Redis).
`CallInfo` and `LeadData` are returned by adapter calls.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID


class SessionStatus(str, Enum):
    LOGGING_IN = "logging_in"
    READY      = "ready"
    ON_CALL    = "on_call"
    PAUSED     = "paused"
    ERROR      = "error"
    LOGGED_OUT = "logged_out"


@dataclass
class DeploymentRow:
    """The subset of `deployments` + joined `vicidial_servers` we need."""
    deployment_id: UUID
    tenant_id: UUID
    vici_server_id: UUID
    web_url: str
    asterisk_host: str
    vici_user: str
    vici_pass: str         # decrypted
    phone_login: str
    phone_pass: str        # decrypted
    campaign_id: str
    allowed_transfer_ingroups: list[str] = field(default_factory=list)


@dataclass
class CapturedSession:
    """What Playwright extracts after a successful login."""
    cookies: dict[str, str]
    conf_exten: str
    session_id: str
    session_name: str = ""
    user_agent: str = ""


@dataclass
class CallInfo:
    """Currently bridged call. Fields are `None` when no call is bridged."""
    lead_id: str | None = None
    uniqueid: str | None = None
    phone_number: str | None = None
    campaign_id: str | None = None
    list_id: str | None = None


@dataclass
class LeadData:
    lead_id: str
    first_name: str = ""
    last_name: str = ""
    phone_number: str = ""
    email: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    custom: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionState:
    """Per-deployment runtime state. JSON-serialisable for Redis mirroring."""

    deployment_id: str
    tenant_id: str
    vici_user: str
    phone_login: str
    campaign: str
    status: SessionStatus = SessionStatus.LOGGING_IN

    # Captured after Playwright login — set to empty until then.
    cookies: dict[str, str] = field(default_factory=dict)
    conf_exten: str = ""
    session_id: str = ""
    session_name: str = ""
    user_agent: str = ""

    last_heartbeat_at: float | None = None
    last_call_id: str | None = None
    login_attempts: int = 0
    heartbeat_failures: int = 0
    last_error: str = ""

    created_at: float = field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )

    def to_redis_payload(self) -> dict[str, str]:
        """Serialise as a flat dict — Redis hash fields are strings."""
        out = asdict(self)
        # Status enum → string.
        out["status"] = self.status.value
        # Cookies dict → JSON string.
        import json
        out["cookies"] = json.dumps(self.cookies)
        # None → empty string for Redis.
        return {k: ("" if v is None else str(v) if not isinstance(v, str) else v)
                for k, v in out.items()}

    @classmethod
    def from_redis_payload(cls, data: dict[str, str]) -> "SessionState":
        import json
        cookies_raw = data.get("cookies") or "{}"
        try:
            cookies = json.loads(cookies_raw)
        except json.JSONDecodeError:
            cookies = {}
        return cls(
            deployment_id=data.get("deployment_id", ""),
            tenant_id=data.get("tenant_id", ""),
            vici_user=data.get("vici_user", ""),
            phone_login=data.get("phone_login", ""),
            campaign=data.get("campaign", ""),
            status=SessionStatus(data.get("status", SessionStatus.LOGGING_IN.value)),
            cookies=cookies,
            conf_exten=data.get("conf_exten", ""),
            session_id=data.get("session_id", ""),
            session_name=data.get("session_name", ""),
            user_agent=data.get("user_agent", ""),
            last_heartbeat_at=float(data["last_heartbeat_at"])
                              if data.get("last_heartbeat_at") else None,
            last_call_id=data.get("last_call_id") or None,
            login_attempts=int(data.get("login_attempts") or 0),
            heartbeat_failures=int(data.get("heartbeat_failures") or 0),
            last_error=data.get("last_error", ""),
            created_at=float(data.get("created_at") or 0),
        )
