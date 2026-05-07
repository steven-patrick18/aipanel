"""F5-TTS backend. Synthesis is sentence-chunked for streaming.

F5-TTS infers full utterances per call; the only way to stream today is to
slice the input text on sentence boundaries and synthesise each piece. The
``f5-tts`` PyPI package is heavyweight (torch, vocos, etc.) so we import it
lazily — that keeps cold-start light when the backend is configured to
``noop`` for dev/test boxes.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import structlog

log = structlog.get_logger().bind(component="f5_backend")

# Sentence splitter — keeps trailing punctuation with the sentence.
_SENT_RE = re.compile(r"(.+?(?:[.!?](?:\s+|$)|\n+|$))", re.S)


def _split_sentences(text: str) -> list[str]:
    parts = [m.group(1).strip() for m in _SENT_RE.finditer(text)]
    return [p for p in parts if p]


class F5Backend:
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
        # Deferred import — torch / f5-tts are multi-second to import.
        from f5_tts.api import F5TTS  # type: ignore[import-not-found]
        log.info("f5_loading", device=self.device)
        self._tts = F5TTS(device=None if self.device == "auto" else self.device)
        log.info("f5_ready")
        return self._tts

    def synthesize(
        self,
        text: str,
        voice_id: str | None,
        speed: float = 1.0,
    ) -> Iterator[np.ndarray]:
        ref_wav, ref_text = self._resolve_voice(voice_id)
        tts = self._ensure_loaded()

        sentences = _split_sentences(text) or [text]
        for s in sentences:
            try:
                audio, sr, _ = tts.infer(
                    ref_file=str(ref_wav),
                    ref_text=ref_text,
                    gen_text=s,
                    speed=speed,
                    remove_silence=False,
                )
            except Exception as exc:                         # pragma: no cover
                log.error("f5_infer_failed",
                          sentence_preview=s[:40], error=str(exc))
                # Yield silence so the stream stays well-formed instead of dying.
                yield np.zeros(int(0.2 * self.sample_rate), dtype=np.float32)
                continue
            arr = np.asarray(audio, dtype=np.float32)
            if sr != self.sample_rate:
                # Should not happen with stock F5 (always 24 kHz) but be safe.
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
        target = self.voices_dir / voice_id
        target.mkdir(parents=True, exist_ok=True)
        ref = target / "ref.wav"
        ref.write_bytes(audio_bytes)
        (target / "ref_text.txt").write_text(ref_text, encoding="utf-8")
        log.info("voice_cloned", voice_id=voice_id, name=voice_name,
                 ref_path=str(ref), bytes=len(audio_bytes))
        return ref

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_voice(self, voice_id: str | None) -> tuple[Path, str]:
        if not voice_id:
            raise ValueError("voice_id is required for the F5 backend")
        vdir = self.voices_dir / voice_id
        ref = vdir / "ref.wav"
        rtxt = vdir / "ref_text.txt"
        if not ref.exists() or not rtxt.exists():
            raise FileNotFoundError(
                f"voice {voice_id} not found at {vdir} "
                f"(need ref.wav + ref_text.txt; clone via POST /v1/tts/clone)"
            )
        return ref, rtxt.read_text(encoding="utf-8").strip()
