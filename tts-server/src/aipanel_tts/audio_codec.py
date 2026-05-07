"""PCM ↔ μ-law (G.711) and resampling helpers.

We use the stdlib ``audioop`` module on Python 3.11/3.12. It's deprecated
in 3.13 — the ``audioop-lts`` PyPI shim is listed in pyproject and is API-
compatible, so the fallback import below works on either runtime.
"""

from __future__ import annotations

import io
import wave

import numpy as np

try:
    import audioop                        # type: ignore[import-untyped]
except ImportError:                                          # pragma: no cover
    import audioop_lts as audioop         # type: ignore[no-redef]


def f32_to_s16(arr: np.ndarray) -> bytes:
    """Float32 in [-1, 1] → little-endian s16 bytes. Clips out-of-range."""
    arr = np.clip(arr, -1.0, 1.0)
    return (arr * 32767.0).astype("<i2").tobytes()


def resample_s16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample s16 mono PCM with audioop's ratecv. State-free per call."""
    if src_rate == dst_rate:
        return pcm
    converted, _ = audioop.ratecv(pcm, 2, 1, src_rate, dst_rate, None)
    return converted


def s16_to_ulaw(pcm: bytes) -> bytes:
    """G.711 μ-law encode of s16 mono PCM. 1 byte per sample."""
    return audioop.lin2ulaw(pcm, 2)


def make_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """Wrap raw s16 PCM in a WAV container — used by /transcribe smoke tests."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Output format dispatch — keep all bytes-shaping in one place.
# ---------------------------------------------------------------------------

VALID_FORMATS = {
    "ulaw_8000",
    "pcm_s16le_8000",
    "pcm_s16le_24000",
}


def encode(pcm_f32: np.ndarray, src_rate: int, fmt: str) -> bytes:
    """Convert the backend's float32 PCM into the requested wire format."""
    if fmt not in VALID_FORMATS:
        raise ValueError(f"unsupported output_format: {fmt}")

    s16 = f32_to_s16(pcm_f32)

    if fmt == "pcm_s16le_24000":
        return resample_s16(s16, src_rate, 24000)
    if fmt == "pcm_s16le_8000":
        return resample_s16(s16, src_rate, 8000)
    # ulaw_8000
    s16_8k = resample_s16(s16, src_rate, 8000)
    return s16_to_ulaw(s16_8k)


def media_type_for(fmt: str) -> str:
    if fmt == "ulaw_8000":
        return "audio/basic"            # IANA: 8 kHz μ-law mono
    return "audio/L16"                  # closest registered type for raw PCM
