"""Pluggable TTS backends. See base.py for the contract."""

from __future__ import annotations

from .base import TTSBackend
from .f5 import F5Backend
from .kokoro import KokoroBackend
from .noop import NoopBackend


def make_backend(name: str, **kwargs) -> TTSBackend:
    if name == "f5":
        return F5Backend(**kwargs)
    if name == "kokoro":
        return KokoroBackend(**kwargs)
    if name == "noop":
        return NoopBackend(**kwargs)
    raise ValueError(f"unknown TTS backend: {name}")


__all__ = ["TTSBackend", "F5Backend", "KokoroBackend", "NoopBackend", "make_backend"]
