"""Backend that synthesises a sine wave. Used for smoke tests + dev boxes
that don't have F5-TTS installed."""

from __future__ import annotations

import math
from collections.abc import Iterator
from pathlib import Path

import numpy as np


class NoopBackend:
    sample_rate = 24000

    def __init__(self, voices_dir: Path | None = None, **_: object) -> None:
        self.voices_dir = voices_dir or Path("/var/lib/aipanel/voices")

    def synthesize(
        self,
        text: str,
        voice_id: str | None,
        speed: float = 1.0,
    ) -> Iterator[np.ndarray]:
        # ~80 ms per character of text at 24 kHz, capped at 4 s, as a
        # 440 Hz sine wave. Chunked into 200 ms blocks so the streaming
        # path actually streams.
        total_sec = max(0.5, min(4.0, len(text) * 0.08 / max(speed, 0.1)))
        total_samples = int(total_sec * self.sample_rate)
        chunk_samples = int(0.2 * self.sample_rate)

        t0 = 0
        while t0 < total_samples:
            t1 = min(t0 + chunk_samples, total_samples)
            t = np.arange(t0, t1, dtype=np.float32) / self.sample_rate
            chunk = 0.2 * np.sin(2.0 * math.pi * 440.0 * t)
            yield chunk
            t0 = t1

    def clone(
        self,
        voice_id: str,
        voice_name: str,
        audio_bytes: bytes,
        ref_text: str,
    ) -> Path:
        target = self.voices_dir / voice_id
        target.mkdir(parents=True, exist_ok=True)
        ref = target / "ref.wav"
        ref.write_bytes(audio_bytes)
        (target / "ref_text.txt").write_text(ref_text, encoding="utf-8")
        return ref
