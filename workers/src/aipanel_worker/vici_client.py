"""HTTP client for the ViciDial Session Manager service.

The Session Manager itself doesn't exist yet (separate prompt). For v0.5
this client is real-on-success / stub-on-failure: every method tries the
HTTP call, and if the configured endpoint is empty or unreachable we return
sensible canned data so the worker pipeline still runs end-to-end.

When the real Session Manager lands, set ``vici.url`` and ``vici.enabled``
in aipanel.conf and the stub paths drop out automatically.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog

log = structlog.get_logger().bind(component="vici_client")


@dataclass
class Lead:
    lead_id: str
    name: str = ""
    phone_number: str = ""
    email: str = ""
    extra: dict | None = None


class ViciClient:
    def __init__(
        self,
        base_url: str,
        enabled: bool,
        timeout_sec: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.enabled = enabled and bool(base_url)
        self._client: httpx.AsyncClient | None = None
        self._timeout = timeout_sec

    async def __aenter__(self) -> "ViciClient":
        if self.enabled:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self._timeout),
            )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get_lead(self, lead_id: str | None) -> Lead:
        if not lead_id:
            return Lead(lead_id="", name="the customer")
        if not self.enabled or self._client is None:
            log.debug("vici_stub_get_lead", lead_id=lead_id)
            return Lead(lead_id=lead_id, name="the customer")
        try:
            r = await self._client.get(f"/api/vici/lead/{lead_id}")
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as exc:
            log.warning("vici_get_lead_failed",
                        lead_id=lead_id, error=str(exc))
            return Lead(lead_id=lead_id, name="the customer")
        return Lead(
            lead_id=str(data.get("lead_id", lead_id)),
            name=data.get("name", "") or data.get("first_name", "") or "the customer",
            phone_number=data.get("phone_number", "") or "",
            email=data.get("email", "") or "",
            extra=data,
        )

    # ------------------------------------------------------------------
    # Writes — every method returns success bool; failures already logged.
    # ------------------------------------------------------------------

    async def post_disposition(
        self,
        *,
        call_id: str,
        vici_uniqueid: str | None,
        dispo_code: str,
        notes: str = "",
    ) -> bool:
        return await self._post(
            "/api/vici/disposition",
            {"call_id": call_id, "vici_uniqueid": vici_uniqueid,
             "dispo_code": dispo_code, "notes": notes},
        )

    async def transfer_to_ingroup(
        self,
        *,
        call_id: str,
        vici_uniqueid: str | None,
        ingroup_id: str,
        summary: str,
    ) -> bool:
        return await self._post(
            "/api/vici/transfer",
            {"call_id": call_id, "vici_uniqueid": vici_uniqueid,
             "ingroup_id": ingroup_id, "summary": summary},
        )

    async def mark_dnc(
        self,
        *,
        vici_lead_id: str | None,
        reason: str,
    ) -> bool:
        return await self._post(
            "/api/vici/dnc",
            {"vici_lead_id": vici_lead_id, "reason": reason},
        )

    async def schedule_callback(
        self,
        *,
        vici_lead_id: str | None,
        when: str,
        notes: str,
    ) -> bool:
        return await self._post(
            "/api/vici/callback",
            {"vici_lead_id": vici_lead_id, "when": when, "notes": notes},
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _post(self, path: str, body: dict) -> bool:
        if not self.enabled or self._client is None:
            log.info("vici_stub_post", path=path, body=body)
            return True
        try:
            r = await self._client.post(path, json=body)
            r.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            log.warning("vici_post_failed", path=path, error=str(exc))
            return False
