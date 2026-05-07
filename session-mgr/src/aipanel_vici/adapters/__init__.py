"""Pluggable ViciDial-version adapters."""

from __future__ import annotations

from .base import VicidialAdapter
from .v2_14 import ViciDialAdapter_2_14


def get_adapter(name: str) -> VicidialAdapter:
    if name in ("v2_14", "2.14", "2_14"):
        return ViciDialAdapter_2_14()
    raise ValueError(f"unknown ViciDial adapter: {name!r}")


__all__ = ["VicidialAdapter", "ViciDialAdapter_2_14", "get_adapter"]
