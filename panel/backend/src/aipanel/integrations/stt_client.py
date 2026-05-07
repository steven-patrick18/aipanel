"""Client for the STT server. Currently used only for /health probing."""

from __future__ import annotations

import httpx


class STTClient:
    def __init__(self, base_url: str, *, timeout_sec: float = 5.0) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base, timeout=httpx.Timeout(timeout_sec),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict | None:
        try:
            r = await self._client.get("/health")
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return None
