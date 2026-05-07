"""Kokoro TTS backend — fast, ONNX-based, sub-300ms first-byte target.

Kokoro doesn't natively support voice cloning the way F5-TTS does. We use
its built-in voice library; the ``voice_id`` parameter maps to a Kokoro
voice name (e.g. "af_bella"). For cloned voices, the operator should keep
the F5 backend on those campaigns.

Streaming
---------

Kokoro generates by sentence. We split on sentence punctuation and yield
each sentence's audio as soon as it's produced — first-byte latency is
typically 150-280ms on GPU, 600-900ms on CPU.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import structlog

log = structlog.get_logger().bind(component="kokoro_backend")

_SENT_RE = re.compile(r"(.+?(?:[.!?](?:\s+|$)|\n+|$))", re.S)
DEFAULT_KOKORO_VOICE = "af_bella"


def _split_sentences(text: str) -> list[str]:
    parts = [m.group(1).strip() for m in _SENT_RE.finditer(text)]
    return [p for p in parts if p]


class KokoroBackend:
    """ONNX-based Kokoro. Sample rate 24 kHz native."""
    sample_rate = 24000

    def __init__(
        self,
        device: str = "auto",
        voices_dir: Path | None = None,
        models_dir: Path | None = None,
        **_: object,
    ) -> None:
        self.device = device
        self.voices_dir = voices_dir or Path("/var/lib/aipanel/voices")
        self.models_dir = models_dir or Path("/var/lib/aipanel/models/tts")
        self._tts: Any = None

    def _ensure_loaded(self) -> Any:
        if self._tts is not None:
            return self._tts
        # The package landscape for Kokoro is in flux — we try the two most
        # common entrypoints. If neither imports, raise something useful.
        try:
            from kokoro_onnx import Kokoro     # type: ignore[import-not-found]
            log.info("kokoro_loading_via_kokoro_onnx", device=self.device)
            model_path = self.models_dir / "kokoro-v0_19.onnx"
            voices_path = self.models_dir / "voices.bin"
            self._tts = Kokoro(str(model_path), str(voices_path))
            return self._tts
        except ImportError:
            pass
        try:
            from kokoro import KPipeline       # type: ignore[import-not-found]
            log.info("kokoro_loading_via_kokoro_pipeline", device=self.device)
            self._tts = KPipeline(lang_code="a")
            return self._tts
        except ImportError as exc:                          # pragma: no cover
            raise RuntimeError(
                "Kokoro is not installed. Run: pip install kokoro-onnx "
                "(or `pip install kokoro` for the PyTorch flavour)."
            ) from exc

    def synthesize(
        self,
        text: str,
        voice_id: str | None,
        speed: float = 1.0,
    ) -> Iterator[np.ndarray]:
        tts = self._ensure_loaded()
        voice = voice_id or DEFAULT_KOKORO_VOICE

        sentences = _split_sentences(text) or [text]
        for sentence in sentences:
            try:
                # kokoro_onnx returns (samples, sr) directly.
                if hasattr(tts, "create"):
                    samples, sr = tts.create(sentence, voice=voice, speed=speed)
                # KPipeline yields (graphemes, phonemes, audio) tuples.
                else:
                    chunks = []
                    for _g, _p, audio in tts(sentence, voice=voice, speed=speed):
                        chunks.append(audio)
                    if not chunks:
                        continue
                    samples = np.concatenate(chunks)
                    sr = self.sample_rate
            except Exception as exc:                        # pragma: no cover
                log.error("kokoro_infer_failed",
                          sentence_preview=sentence[:40], error=str(exc))
                yield np.zeros(int(0.2 * self.sample_rate), dtype=np.float32)
                continue

            arr = np.asarray(samples, dtype=np.float32)
            if sr != self.sample_rate:
                ratio = self.sample_rate / sr
                arr = np.interp(
                    np.linspace(0.0, arr.size, int(arr.size * ratio),
                                endpoint=False),
                    np.arange(arr.size),
                    arr,
                ).astype(np.float32)
            yield arr

    def clone(
        self,
        voice_id: str,
        voice_name: str,
        audio_bytes: bytes,
        ref_text: str,
    ) -> Path:
        # Kokoro doesn't do per-customer cloning — voices are pre-trained.
        # Operators wanting cloned voices should set [tts] backend = "f5".
        # We still write the reference clip to disk so the F5 backend can
        # be swapped to without re-uploading.
        target = self.voices_dir / voice_id
        target.mkdir(parents=True, exist_ok=True)
        ref = target / "ref.wav"
        ref.write_bytes(audio_bytes)
        (target / "ref_text.txt").write_text(ref_text, encoding="utf-8")
        log.warning("kokoro_clone_noop",
                    voice_id=voice_id,
                    note="ref clip saved but Kokoro can't use it; switch "
                         "campaign to backend=f5 to use this voice")
        return ref
