"""Backend interface for TTS.

Two operations:

* ``synthesize(text, voice_id, speed)`` is a generator that yields chunks of
  float32 PCM at ``self.sample_rate``. Implementations should yield at
  natural boundaries (sentence, sub-sentence) to minimise time-to-first-
  byte. The HTTP layer wraps the chunks in the requested wire format.
* ``clone(voice_id, voice_name, audio_bytes, ref_text)`` registers a new
  voice and returns the path the server should remember as
  ``embedding_path``. F5-TTS treats the reference audio + text as the
  "embedding" — there's no separate vector to store.
"""

from __future__ import annotations

import abc
from collections.abc import Iterator
from pathlib import Path

import numpy as np


class TTSBackend(abc.ABC):
    sample_rate: int

    @abc.abstractmethod
    def synthesize(
        self,
        text: str,
        voice_id: str | None,
        speed: float = 1.0,
    ) -> Iterator[np.ndarray]:
        """Yield float32 PCM mono chunks at ``self.sample_rate``."""

    @abc.abstractmethod
    def clone(
        self,
        voice_id: str,
        voice_name: str,
        audio_bytes: bytes,
        ref_text: str,
    ) -> Path:
        """Persist a new voice; return the path used as ``embedding_path``."""

    def shutdown(self) -> None:
        """Optional teardown hook. Backends with GPU state override this."""
