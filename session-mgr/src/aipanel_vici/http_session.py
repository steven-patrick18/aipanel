"""httpx wrapper that holds the captured cookie jar for one ViciDial session.

The adapter produces ``HttpRequestSpec``; this module turns that into a real
httpx call against the deployment's ``web_url`` base, with the right cookies
applied.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from .adapters.base import HttpRequestSpec, VicidialAdapter
from .adapters.v2_14 import base_url_from
from .models import CapturedSession, DeploymentRow

log = structlog.get_logger().bind(component="http_session")


class ViciHttp:
    """One per active session. Reuses an HTTP/1.1 connection (vici is old PHP)."""

    def __init__(
        self,
        deployment: DeploymentRow,
        captured: CapturedSession,
        *,
        timeout_sec: float = 8.0,
    ) -> None:
        self.deployment = deployment
        self.captured = captured
        base_url = base_url_from(deployment.web_url)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            cookies=captured.cookies,
            timeout=httpx.Timeout(timeout_sec, connect=4.0),
            verify=False,                # many vici installs use self-signed
            headers={
                "User-Agent": captured.user_agent
                              or "aipanel-session-mgr/0.6",
                "X-Requested-With": "XMLHttpRequest",
            },
            http2=False,                 # ViciDial Apache rarely speaks h2
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Sending adapter-built requests
    # ------------------------------------------------------------------

    async def send(
        self,
        adapter: VicidialAdapter,
        spec: HttpRequestSpec,
    ) -> tuple[int, str]:
        """Issue the spec; return (status_code, body_text). Never raises on HTTP errors."""
        try:
            response = await self._client.request(
                spec.method,
                spec.path,
                params=spec.params,
                data=spec.data,
                json=spec.json,
            )
        except httpx.TimeoutException:
            return 599, ""
        except httpx.HTTPError as exc:
            log.warning("vici_request_failed",
                        path=spec.path, error=str(exc))
            return 0, ""
        return response.status_code, response.text

    def detect_session_expired(
        self,
        adapter: VicidialAdapter,
        status_code: int,
        body: str,
    ) -> bool:
        return adapter.is_response_session_expired(body, status_code)

    # ------------------------------------------------------------------
    # Cookie jar updates (some adapter calls return Set-Cookie)
    # ------------------------------------------------------------------

    def refresh_cookies(self) -> dict[str, str]:
        """Snapshot the current cookie jar for persistence to Redis."""
        out: dict[str, str] = {}
        for c in self._client.cookies.jar:
            if c.name:
                out[c.name] = c.value or ""
        return out
