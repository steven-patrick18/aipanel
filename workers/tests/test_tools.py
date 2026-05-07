"""Tests for tools — schema shape + dispatcher behaviour."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from aipanel_worker.tools import (
    TERMINAL_TOOLS,
    TOOL_SCHEMAS,
    ToolContext,
    dispatch,
)


# ---------------------------------------------------------------------------
# Minimal stubs for ToolContext deps
# ---------------------------------------------------------------------------

class _ViciStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def transfer_to_ingroup(self, **kw):
        self.calls.append(("transfer", kw))
        return True

    async def mark_dnc(self, **kw):
        self.calls.append(("dnc", kw))
        return True

    async def schedule_callback(self, **kw):
        self.calls.append(("cb", kw))
        return True


class _KBStub:
    def __init__(self, results: list[str]) -> None:
        self._results = results

    async def search(self, q: str, limit: int = 5) -> list[str]:
        return self._results


@dataclass
class _TWStub:
    written: list[tuple[str, dict]]

    def write(self, etype: str, payload: dict) -> None:
        self.written.append((etype, payload))


def _ctx(*, kb_results=None, with_writer=True) -> ToolContext:
    return ToolContext(
        call_id="c1",
        deployment_id="d1",
        vici_lead_id="L1",
        vici_uniqueid="V1",
        vici_client=_ViciStub(),
        kb_search=_KBStub(kb_results or []),
        transcript_writer=_TWStub([]) if with_writer else None,
    )


# ---------------------------------------------------------------------------
# Schema sanity
# ---------------------------------------------------------------------------

def test_each_schema_has_function_name_and_params():
    for s in TOOL_SCHEMAS:
        assert s["type"] == "function"
        f = s["function"]
        assert "name" in f and isinstance(f["name"], str)
        assert "description" in f
        assert f["parameters"]["type"] == "object"


def test_terminal_tools_are_subset_of_schema_names():
    schema_names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert TERMINAL_TOOLS.issubset(schema_names)


# ---------------------------------------------------------------------------
# Dispatcher routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_tool_returns_failure():
    res = await dispatch("does_not_exist", {}, _ctx())
    assert res.success is False
    assert "Unknown tool" in res.feedback_to_llm


@pytest.mark.asyncio
async def test_malformed_json_args_handled():
    res = await dispatch("end_call", "not-json", _ctx())
    assert res.success is False
    assert "JSON" in res.feedback_to_llm


@pytest.mark.asyncio
async def test_search_kb_returns_no_results():
    res = await dispatch("search_kb", '{"query":"warranty"}', _ctx(kb_results=[]))
    assert res.success is True
    assert res.is_terminal is False
    assert "No results" in res.feedback_to_llm


@pytest.mark.asyncio
async def test_search_kb_returns_top_results():
    res = await dispatch(
        "search_kb",
        '{"query":"warranty"}',
        _ctx(kb_results=["1y limited", "extended available"]),
    )
    assert res.success is True
    assert "1y limited" in res.feedback_to_llm
    assert "extended available" in res.feedback_to_llm


@pytest.mark.asyncio
async def test_dispose_qualified_is_terminal():
    res = await dispatch(
        "dispose_qualified", '{"notes":"ready to buy"}', _ctx()
    )
    assert res.success is True
    assert res.is_terminal is True
    assert res.dispo_code == "QUAL"
    assert res.speak  # acknowledgment text exists


@pytest.mark.asyncio
async def test_transfer_to_ingroup_calls_vici():
    ctx = _ctx()
    res = await dispatch(
        "transfer_to_ingroup",
        '{"ingroup_id":"SALES","reason":"buyer","summary_for_agent":"hot lead"}',
        ctx,
    )
    assert res.success is True
    assert res.is_terminal is True
    assert ctx.vici_client.calls[0][0] == "transfer"
    assert ctx.vici_client.calls[0][1]["ingroup_id"] == "SALES"


@pytest.mark.asyncio
async def test_transcript_writer_records_tool_calls():
    ctx = _ctx()
    await dispatch("end_call", '{"reason":"caller said goodbye"}', ctx)
    written = ctx.transcript_writer.written
    assert any(e[0] == "tool_call" and e[1]["name"] == "end_call" for e in written)


@pytest.mark.asyncio
async def test_transfer_missing_ingroup_id_fails():
    res = await dispatch(
        "transfer_to_ingroup",
        '{"reason":"x","summary_for_agent":"y"}',
        _ctx(),
    )
    assert res.success is False
    assert res.is_terminal is False
