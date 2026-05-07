"""Render the LLM system prompt from an agent config + lead context.

Uses Jinja2 with ``ChainableUndefined`` so missing dotted lookups silently
render as empty strings rather than raising. Real production would prefer
strict mode after the agent schema stabilises; for v0.5 the loose default
keeps half-populated agent rows usable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jinja2

from .humanize import DEFAULT_DISCLOSURE
from .methodologies import get_methodology_section

DEFAULT_SYSTEM_PROMPT = """\
You are {{ persona.name | default("an AI assistant") }}, {{ persona.description | default("a helpful agent on a phone call") }}.
You are calling {{ lead.name | default("the customer") }} regarding {{ campaign.purpose | default("today's outreach") }}.

GUIDELINES:
- Speak naturally and conversationally. You are on a phone call.
- Keep responses under {{ max_response_words | default(30) }} words unless explaining something complex.
- Listen to the customer. Acknowledge what they say before responding.
- If asked "are you a robot/AI/human", respond honestly: "{{ disclosure_response }}"
{%- if additional_guidelines %}
- {{ additional_guidelines }}
{%- endif %}

{%- if methodology_section %}

{{ methodology_section }}
{%- endif %}

{%- if campaign_objective %}

CAMPAIGN OBJECTIVE: {{ campaign_objective }}
{%- endif %}

CONVERSATION FLOW:
{{ script.opening | default("") }}
{%- if script.sections %}
{{ render_sections(script.sections) }}
{%- endif %}
{{ script.closing | default("") }}

{%- if objections %}

OBJECTION HANDLING:
{{ render_objections(objections) }}
{%- endif %}

{%- if few_shot_examples %}

EXAMPLES OF EXCHANGES THAT WORKED ON THIS CAMPAIGN
(mined from your own previous successful calls — match this tone and rhythm):
{{ render_few_shot(few_shot_examples) }}
{%- endif %}

{%- if kb_enabled %}

KNOWLEDGE BASE:
You have access to the search_kb tool for product/policy questions.
{%- endif %}

OUTCOMES:
You can use these tools to end or transfer the call:
{{ render_tool_descriptions(tools) }}
"""

# The full methodology system-prompt scaffolding lives in
# ``methodologies.py``. ``get_methodology_section(key)`` returns the
# multi-paragraph block that gets injected into the prompt. Source-of-truth
# is panel/backend/src/aipanel/sales_lib/data.py — sync after edits.


# ---------------------------------------------------------------------------
# Custom filters / globals
# ---------------------------------------------------------------------------

def _render_sections(sections: Any) -> str:
    if not sections:
        return ""
    if isinstance(sections, str):
        return sections
    if isinstance(sections, list):
        return "\n".join(f"- {s}" for s in sections)
    if isinstance(sections, dict):
        return "\n".join(f"- {k}: {v}" for k, v in sections.items())
    return str(sections)


def _render_objections(objections: Any) -> str:
    if not objections:
        return ""
    if isinstance(objections, list):
        return "\n".join(f"- {o}" for o in objections)
    if isinstance(objections, dict):
        return "\n".join(f"- If they say \"{q}\": {a}" for q, a in objections.items())
    return str(objections)


def _render_tool_descriptions(tools: list[dict] | None) -> str:
    if not tools:
        return "(none)"
    out = []
    for t in tools:
        fn = t.get("function", t)
        name = fn.get("name", "?")
        desc = fn.get("description", "").strip()
        out.append(f"- {name}: {desc}")
    return "\n".join(out)


def _render_few_shot(examples: list[dict] | None) -> str:
    """Render the campaign's mined few-shot pool as User/Agent pairs."""
    if not examples:
        return ""
    out: list[str] = []
    for i, ex in enumerate(examples, 1):
        u = (ex.get("user") or "").strip()
        a = (ex.get("agent") or "").strip()
        if not u or not a:
            continue
        out.append(f"Example {i}:")
        out.append(f"  Customer: {u}")
        out.append(f"  You:      {a}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromptContext:
    persona: dict
    lead: dict
    campaign: dict
    script: dict
    objections: Any = None
    additional_guidelines: str = ""
    disclosure_response: str = DEFAULT_DISCLOSURE
    max_response_words: int = 30
    kb_enabled: bool = False
    tools: list[dict] | None = None
    # Per-campaign extras (added in v0.10):
    methodology: str = ""           # spin | bant | meddpicc | consultative | value_based | custom
    campaign_objective: str = ""    # human-readable goal, e.g. "book a 15-min demo"
    few_shot_examples: list[dict] | None = None


def make_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.BaseLoader(),
        undefined=jinja2.ChainableUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["render_sections"] = _render_sections
    env.globals["render_objections"] = _render_objections
    env.globals["render_tool_descriptions"] = _render_tool_descriptions
    env.globals["render_few_shot"] = _render_few_shot
    return env


def build_system_prompt(
    ctx: PromptContext,
    template_str: str | None = None,
) -> str:
    """Render the system prompt. ``template_str`` overrides the default."""
    env = make_env()
    template = env.from_string(template_str or DEFAULT_SYSTEM_PROMPT)
    return template.render(
        persona=ctx.persona or {},
        lead=ctx.lead or {},
        campaign=ctx.campaign or {},
        script=ctx.script or {},
        objections=ctx.objections,
        additional_guidelines=ctx.additional_guidelines,
        disclosure_response=ctx.disclosure_response,
        max_response_words=ctx.max_response_words,
        kb_enabled=ctx.kb_enabled,
        tools=ctx.tools,
        methodology=ctx.methodology,
        methodology_section=get_methodology_section(ctx.methodology),
        campaign_objective=ctx.campaign_objective,
        few_shot_examples=ctx.few_shot_examples or [],
    ).strip()
