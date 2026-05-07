"""HTTP client for the embed-server."""

from __future__ import annotations

import httpx
import structlog

log = structlog.get_logger().bind(component="embed_client")


class EmbedClient:
    def __init__(self, base_url: str, *, timeout_sec: float = 30.0) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=httpx.Timeout(timeout_sec, connect=5.0),
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

    async def embed(self, text: str) -> list[float] | None:
        try:
            r = await self._client.post("/v1/embed", json={"text": text})
            r.raise_for_status()
            return r.json()["embedding"]
        except httpx.HTTPError as exc:
            log.warning("embed_failed", error=str(exc))
            return None

    async def embed_batch(self, texts: list[str]) -> list[list[float]] | None:
        try:
            r = await self._client.post("/v1/embed/batch", json={"texts": texts})
            r.raise_for_status()
            return r.json()["embeddings"]
        except httpx.HTTPError as exc:
            log.warning("embed_batch_failed", error=str(exc))
            return None
