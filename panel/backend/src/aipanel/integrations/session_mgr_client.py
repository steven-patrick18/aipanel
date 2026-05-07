"""Client for the ViciDial Session Manager (prompt 8)."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

log = structlog.get_logger().bind(component="session_mgr_client")


class SessionMgrClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_sec: float = 5.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"X-AIPanel-Token": token}
        self._timeout = timeout_sec

    async def __aenter__(self) -> "SessionMgrClient":
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=httpx.Timeout(self._timeout),
            headers=self._headers,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def status(self, deployment_id: str) -> dict[str, Any] | None:
        try:
            r = await self._client.get(f"/api/v1/deployments/{deployment_id}/status")
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as exc:
            log.warning("session_mgr_status_failed",
                        deployment_id=deployment_id, error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def start(self, deployment_id: str) -> bool:
        return await self._post(f"/api/v1/deployments/{deployment_id}/start")

    async def stop(self, deployment_id: str) -> bool:
        return await self._post(f"/api/v1/deployments/{deployment_id}/stop")

    async def pause(self, deployment_id: str, pause_code: str) -> bool:
        return await self._post(
            f"/api/v1/deployments/{deployment_id}/pause",
            json={"pause_code": pause_code},
        )

    async def hangup(self, deployment_id: str) -> bool:
        return await self._post(f"/api/v1/deployments/{deployment_id}/hangup")

    async def transfer(
        self,
        deployment_id: str,
        ingroup_id: str,
        summary: str = "",
    ) -> tuple[bool, str | None]:
        """Bridge the live call into a ViciDial ingroup conference.

        Returns (ok, error_detail). The dialler keeps the customer leg up
        and warm-transfers it; the AI agent leg is dropped after the
        handoff. ``ingroup_id`` must already be configured on the
        ViciDial campaign.
        """
        try:
            r = await self._client.post(
                f"/api/v1/deployments/{deployment_id}/transfer",
                json={"ingroup_id": ingroup_id, "summary": summary},
            )
            if r.status_code >= 400:
                detail = None
                try:
                    detail = r.json().get("detail")
                except Exception:
                    detail = r.text[:200]
                log.warning("session_mgr_transfer_failed",
                            deployment_id=deployment_id,
                            ingroup_id=ingroup_id,
                            status=r.status_code, detail=detail)
                return False, detail or f"HTTP {r.status_code}"
            return True, None
        except httpx.HTTPError as exc:
            log.warning("session_mgr_transfer_error",
                        deployment_id=deployment_id,
                        ingroup_id=ingroup_id, error=str(exc))
            return False, str(exc)

    async def manual_dial(self, deployment_id: str, phone_number: str) -> tuple[bool, str | None]:
        """Originate an outbound test call. Returns (ok, error_detail)."""
        try:
            r = await self._client.post(
                f"/api/v1/deployments/{deployment_id}/manual-dial",
                json={"phone_number": phone_number},
            )
            if r.status_code >= 400:
                detail = None
                try:
                    detail = r.json().get("detail")
                except Exception:
                    detail = r.text[:200]
                log.warning("session_mgr_manual_dial_failed",
                            deployment_id=deployment_id,
                            status=r.status_code, detail=detail)
                return False, detail or f"HTTP {r.status_code}"
            return True, None
        except httpx.HTTPError as exc:
            log.warning("session_mgr_manual_dial_error",
                        deployment_id=deployment_id, error=str(exc))
            return False, str(exc)

    async def _post(self, path: str, json: dict | None = None) -> bool:
        try:
            r = await self._client.post(path, json=json or {})
            r.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            log.warning("session_mgr_post_failed", path=path, error=str(exc))
            return False
