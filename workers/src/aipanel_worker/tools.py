"""Tool definitions for the LLM + dispatcher.

The schemas follow the OpenAI function-calling shape so vLLM's hermes parser
emits them as ``message.tool_calls``. Two categories:

* **Informational** (``search_kb``) — return a string the LLM continues with.
* **Terminal** (``end_call``, ``transfer_to_ingroup``, ``mark_dnc``,
  ``schedule_callback``, ``dispose_*``) — speak an acknowledgement, then hang up.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog

from .metrics import M_TOOL_CALLS

log = structlog.get_logger().bind(component="tools")


# ---------------------------------------------------------------------------
# Schema definitions
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": "Search the knowledge base for product or policy info. "
                           "Use this whenever the caller asks something factual you "
                           "are not 100% sure about.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "Natural-language question to search for."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transfer_to_ingroup",
            "description": "Transfer the call to a human-staffed ViciDial in-group.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ingroup_id": {"type": "string"},
                    "reason":     {"type": "string"},
                    "summary_for_agent": {"type": "string",
                                          "description": "1-2 sentence handoff summary."},
                },
                "required": ["ingroup_id", "reason", "summary_for_agent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_dnc",
            "description": "Mark this number Do-Not-Call.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_callback",
            "description": "Schedule a callback at a specific time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "when":  {"type": "string", "description": "ISO 8601 datetime."},
                    "notes": {"type": "string"},
                },
                "required": ["when", "notes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dispose_not_interested",
            "description": "End the call with a not-interested disposition.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dispose_qualified",
            "description": "End the call with a qualified-lead disposition.",
            "parameters": {
                "type": "object",
                "properties": {"notes": {"type": "string"}},
                "required": ["notes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_call",
            "description": "End the call when no other tool fits (e.g. caller hung up "
                           "verbally, or the conversation has reached its natural end).",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
]


TERMINAL_TOOLS = frozenset({
    "transfer_to_ingroup",
    "mark_dnc",
    "schedule_callback",
    "dispose_not_interested",
    "dispose_qualified",
    "end_call",
})


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    name: str
    success: bool
    is_terminal: bool
    speak: str = ""              # optional spoken acknowledgement
    feedback_to_llm: str = ""    # informational result fed back as a tool message
    dispo_code: str = ""         # ViciDial disposition to post on hangup
    extra: dict[str, Any] = field(default_factory=dict)


# Async tool functions: receive (args_dict, context) → ToolResult.
ToolFn = Callable[[dict, "ToolContext"], Awaitable[ToolResult]]


@dataclass
class ToolContext:
    """Per-call dependencies handed to every tool implementation."""
    call_id: str
    deployment_id: str
    vici_lead_id: str | None
    vici_uniqueid: str | None
    vici_client: Any        # vici_client.ViciClient
    kb_search: Any          # kb_search.KBSearch
    transcript_writer: Any  # transcript_writer.TranscriptWriter | None


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

async def _t_search_kb(args: dict, ctx: ToolContext) -> ToolResult:
    query = args.get("query", "").strip()
    if not query:
        return ToolResult("search_kb", False, False,
                          feedback_to_llm="Empty query.")
    results = await ctx.kb_search.search(query)
    if not results:
        return ToolResult("search_kb", True, False,
                          feedback_to_llm="No results found.")
    summary = "\n".join(f"- {r}" for r in results[:5])
    return ToolResult("search_kb", True, False,
                      feedback_to_llm=f"Top results:\n{summary}")


async def _t_transfer(args: dict, ctx: ToolContext) -> ToolResult:
    ingroup = args.get("ingroup_id", "")
    reason = args.get("reason", "")
    summary = args.get("summary_for_agent", "")
    if not ingroup:
        return ToolResult("transfer_to_ingroup", False, False,
                          feedback_to_llm="ingroup_id is required.")
    ok = await ctx.vici_client.transfer_to_ingroup(
        call_id=ctx.call_id, vici_uniqueid=ctx.vici_uniqueid,
        ingroup_id=ingroup, summary=summary,
    )
    if not ok:
        return ToolResult("transfer_to_ingroup", False, False,
                          feedback_to_llm="Transfer failed; please try a different action.")
    return ToolResult(
        "transfer_to_ingroup", True, True,
        speak="Sure — transferring you now, please hold.",
        dispo_code="XFER",
        extra={"ingroup_id": ingroup, "reason": reason, "summary": summary},
    )


async def _t_dnc(args: dict, ctx: ToolContext) -> ToolResult:
    reason = args.get("reason", "")
    await ctx.vici_client.mark_dnc(
        vici_lead_id=ctx.vici_lead_id, reason=reason
    )
    return ToolResult(
        "mark_dnc", True, True,
        speak="Understood — I've added you to our do-not-call list. Have a good day.",
        dispo_code="DNC",
        extra={"reason": reason},
    )


async def _t_callback(args: dict, ctx: ToolContext) -> ToolResult:
    when = args.get("when", "")
    notes = args.get("notes", "")
    ok = await ctx.vici_client.schedule_callback(
        vici_lead_id=ctx.vici_lead_id, when=when, notes=notes,
    )
    if not ok:
        return ToolResult("schedule_callback", False, False,
                          feedback_to_llm="Couldn't schedule the callback. Try a different time.")
    return ToolResult(
        "schedule_callback", True, True,
        speak="Got it — I've scheduled a callback. Talk to you then.",
        dispo_code="CALLBK",
        extra={"when": when, "notes": notes},
    )


async def _t_dispose_not_interested(args: dict, ctx: ToolContext) -> ToolResult:
    return ToolResult(
        "dispose_not_interested", True, True,
        speak="Thanks for your time. Have a good day.",
        dispo_code="NI",
        extra={"reason": args.get("reason", "")},
    )


async def _t_dispose_qualified(args: dict, ctx: ToolContext) -> ToolResult:
    return ToolResult(
        "dispose_qualified", True, True,
        speak="Wonderful — I'll get this over to the team and they'll be in touch shortly.",
        dispo_code="QUAL",
        extra={"notes": args.get("notes", "")},
    )


async def _t_end_call(args: dict, ctx: ToolContext) -> ToolResult:
    return ToolResult(
        "end_call", True, True,
        speak="Thanks — have a good day.",
        dispo_code="DONE",
        extra={"reason": args.get("reason", "")},
    )


_DISPATCH: dict[str, ToolFn] = {
    "search_kb":              _t_search_kb,
    "transfer_to_ingroup":    _t_transfer,
    "mark_dnc":               _t_dnc,
    "schedule_callback":      _t_callback,
    "dispose_not_interested": _t_dispose_not_interested,
    "dispose_qualified":      _t_dispose_qualified,
    "end_call":               _t_end_call,
}


async def dispatch(name: str, raw_args: str | dict, ctx: ToolContext) -> ToolResult:
    """Run a tool by name. Catches malformed args and unknown tools."""
    fn = _DISPATCH.get(name)
    if fn is None:
        log.warning("tool_unknown", name=name)
        M_TOOL_CALLS.labels(tool="unknown").inc()
        return ToolResult(
            name=name, success=False, is_terminal=False,
            feedback_to_llm=f"Unknown tool '{name}'. Choose from: {sorted(_DISPATCH)}",
        )

    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError as exc:
            log.warning("tool_bad_json", name=name, error=str(exc))
            M_TOOL_CALLS.labels(tool=name).inc()
            return ToolResult(
                name=name, success=False, is_terminal=False,
                feedback_to_llm=f"Tool args were not valid JSON: {exc}.",
            )
    else:
        args = raw_args or {}

    M_TOOL_CALLS.labels(tool=name).inc()
    try:
        result = await fn(args, ctx)
    except Exception as exc:                                 # pragma: no cover
        log.exception("tool_crashed", name=name, error=str(exc))
        return ToolResult(
            name=name, success=False, is_terminal=False,
            feedback_to_llm=f"Tool failed internally: {type(exc).__name__}.",
        )

    if ctx.transcript_writer is not None:
        ctx.transcript_writer.write("tool_call", {
            "name": name,
            "args": args,
            "success": result.success,
            "terminal": result.is_terminal,
            "extra": result.extra,
        })
    return result
