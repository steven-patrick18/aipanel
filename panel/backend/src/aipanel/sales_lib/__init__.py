"""Sales methodology library.

Source-of-truth for the methodology system-prompt scaffolding. The worker
keeps a copy at ``workers/src/aipanel_worker/methodologies.py`` (separate
venv); both files MUST stay in sync — see the worker module's note.

Public API::

    from aipanel.sales_lib import (
        METHODOLOGIES,
        get_methodology,
        list_methodologies,
        render_system_prompt_section,
    )
"""

from __future__ import annotations

from .data import METHODOLOGIES, MethodologyData


def list_methodologies() -> list[MethodologyData]:
    """Return every methodology in display order."""
    return list(METHODOLOGIES.values())


def get_methodology(key: str) -> MethodologyData | None:
    """Lookup by key. Returns None if unknown — caller handles default."""
    return METHODOLOGIES.get(key)


def render_system_prompt_section(key: str) -> str:
    """Render the system-prompt section for a methodology, or '' if unknown."""
    m = METHODOLOGIES.get(key)
    if m is None:
        return ""
    return m["system_prompt"].strip()


__all__ = [
    "METHODOLOGIES",
    "MethodologyData",
    "list_methodologies",
    "get_methodology",
    "render_system_prompt_section",
]
