"""Client for the TTS server (prompt 5)."""

from __future__ import annotations

from typing import AsyncIterator
from uuid import UUID

import httpx
import structlog

log = structlog.get_logger().bind(component="tts_client")


class TTSClient:
    def __init__(self, base_url: str, *, timeout_sec: float = 60.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_sec

    async def __aenter__(self) -> "TTSClient":
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=httpx.Timeout(self._timeout, connect=5.0),
        )
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def health(self) -> dict | None:
        try:
            r = await self._client.get("/health")
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return None

    async def clone(
        self,
        *,
        voice_name: str,
        tenant_id: UUID,
        ref_text: str,
        audio: bytes,
        filename: str = "ref.wav",
    ) -> dict | None:
        files = {"audio": (filename, audio, "audio/wav")}
        data = {
            "voice_name": voice_name,
            "tenant_id":  str(tenant_id),
            "ref_text":   ref_text,
        }
        try:
            r = await self._client.post("/v1/tts/clone", data=data, files=files)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as exc:
            log.warning("tts_clone_failed", error=str(exc))
            return None

    async def synthesize_stream(
        self,
        *,
        text: str,
        voice_id: str | None = None,
        output_format: str = "pcm_s16le_24000",
    ) -> AsyncIterator[bytes]:
        body = {"text": text, "voice_id": voice_id, "output_format": output_format}
        async with self._client.stream("POST", "/v1/tts/synthesize", json=body) as r:
            r.raise_for_status()
            async for chunk in r.aiter_bytes():
                yield chunk
