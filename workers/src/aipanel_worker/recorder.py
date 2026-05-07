"""Per-call audio recording.

v0.5 captures a single mono mix at 8 kHz s16le. Caller and AI samples are
summed with overflow guarding, then written incrementally so a crash mid-
call still yields a valid (truncated) WAV. The file is uploaded to MinIO at
end-of-call and the local copy removed.

Stereo split (caller-left, AI-right) needs sample-aligned interleaving and
is intentionally out of scope for this version — flagged in the response.
"""

from __future__ import annotations

import os
import struct
import wave
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger().bind(component="recorder")


class Recorder:
    def __init__(
        self,
        call_id: str,
        directory: Path,
        *,
        sample_rate: int = 8000,
    ) -> None:
        self.call_id = call_id
        self.path = directory / f"aipanel-rec-{call_id}.wav"
        self.sample_rate = sample_rate

        # Per-direction buffers; we drain whichever is shorter to keep the
        # mono mix roughly time-aligned. Each holds raw s16le bytes.
        self._inbound = bytearray()
        self._outbound = bytearray()
        self._wf: wave.Wave_write | None = None
        self._closed = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._wf = wave.open(str(self.path), "wb")
        self._wf.setnchannels(1)
        self._wf.setsampwidth(2)
        self._wf.setframerate(self.sample_rate)

    def close(self) -> Path | None:
        if self._closed:
            return self.path if self.path.exists() else None
        self._closed = True
        # Drain whichever side has remaining samples by mixing against silence.
        self._mix_and_write(flush=True)
        if self._wf is not None:
            try:
                self._wf.close()
            except Exception:                                # pragma: no cover
                log.exception("wave_close_failed", call_id=self.call_id)
        return self.path if self.path.exists() else None

    # ------------------------------------------------------------------
    # Frame ingest (called from PJSIP-thread-equivalent paths)
    # ------------------------------------------------------------------

    def write_inbound(self, pcm_s16le: bytes) -> None:
        if self._closed or self._wf is None:
            return
        self._inbound.extend(pcm_s16le)
        self._mix_and_write(flush=False)

    def write_outbound(self, pcm_s16le: bytes) -> None:
        if self._closed or self._wf is None:
            return
        self._outbound.extend(pcm_s16le)
        self._mix_and_write(flush=False)

    # ------------------------------------------------------------------
    # Internal: sample-by-sample mix with int16 saturation
    # ------------------------------------------------------------------

    def _mix_and_write(self, flush: bool) -> None:
        # Mix by the minimum of the two buffer lengths (paired samples).
        # On flush, also drain whichever side has leftovers (against silence).
        pair_len = min(len(self._inbound), len(self._outbound))
        if pair_len:
            self._emit_paired(pair_len)
        if not flush:
            return
        leftover = max(len(self._inbound), len(self._outbound))
        if leftover:
            self._emit_solo(leftover)

    def _emit_paired(self, n_bytes: int) -> None:
        # n_bytes must be even (whole samples).
        n_bytes -= n_bytes % 2
        if n_bytes == 0:
            return
        a = bytes(self._inbound[:n_bytes])
        b = bytes(self._outbound[:n_bytes])
        del self._inbound[:n_bytes]
        del self._outbound[:n_bytes]
        out = bytearray(n_bytes)
        for i in range(0, n_bytes, 2):
            sa = struct.unpack_from("<h", a, i)[0]
            sb = struct.unpack_from("<h", b, i)[0]
            mixed = sa + sb
            if mixed > 32767:
                mixed = 32767
            elif mixed < -32768:
                mixed = -32768
            struct.pack_into("<h", out, i, mixed)
        if self._wf is not None:
            self._wf.writeframes(bytes(out))

    def _emit_solo(self, n_bytes: int) -> None:
        n_bytes -= n_bytes % 2
        if n_bytes == 0:
            self._inbound.clear()
            self._outbound.clear()
            return
        if len(self._inbound) >= len(self._outbound):
            data = bytes(self._inbound[:n_bytes])
            self._inbound.clear()
            self._outbound.clear()
        else:
            data = bytes(self._outbound[:n_bytes])
            self._inbound.clear()
            self._outbound.clear()
        if self._wf is not None:
            self._wf.writeframes(data)


# ---------------------------------------------------------------------------
# MinIO upload helper
# ---------------------------------------------------------------------------

async def upload_recording(
    *,
    minio_client: Any,
    bucket: str,
    object_name: str,
    local_path: Path,
    delete_local: bool = True,
) -> str | None:
    """Upload a finished recording. Returns the S3-style key or None on failure."""
    if minio_client is None or not local_path.exists():
        return None
    import asyncio
    try:
        await asyncio.to_thread(
            minio_client.fput_object,
            bucket,
            object_name,
            str(local_path),
            content_type="audio/wav",
        )
    except Exception as exc:
        log.warning("recording_upload_failed",
                    object=object_name, error=str(exc))
        return None
    if delete_local:
        try:
            os.unlink(local_path)
        except OSError:
            pass
    log.info("recording_uploaded", bucket=bucket, key=object_name)
    return object_name
