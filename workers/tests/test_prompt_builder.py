"""Tests for prompt_builder — Jinja rendering correctness."""

from __future__ import annotations

import pytest

from aipanel_worker.prompt_builder import PromptContext, build_system_prompt


def _basic_ctx(**overrides) -> PromptContext:
    base = dict(
        persona={"name": "Sam", "description": "a friendly outreach agent"},
        lead={"name": "Pat Doe"},
        campaign={"purpose": "scheduling a quick demo"},
        script={
            "opening": "Hi, this is Sam.",
            "sections": ["confirm interest", "book demo"],
            "closing": "Thanks for your time.",
        },
        objections={"too busy": "I can keep this short."},
        tools=[
            {"function": {"name": "end_call", "description": "End the call."}},
            {"function": {"name": "transfer_to_ingroup",
                          "description": "Transfer to a human agent."}},
        ],
    )
    base.update(overrides)
    return PromptContext(**base)


def test_persona_and_lead_render():
    out = build_system_prompt(_basic_ctx())
    assert "Sam" in out
    assert "Pat Doe" in out
    assert "scheduling a quick demo" in out


def test_script_sections_rendered_as_bullets():
    out = build_system_prompt(_basic_ctx())
    assert "- confirm interest" in out
    assert "- book demo" in out


def test_objection_rendering():
    out = build_system_prompt(_basic_ctx())
    assert "too busy" in out
    assert "I can keep this short." in out


def test_tools_descriptions_listed():
    out = build_system_prompt(_basic_ctx())
    assert "- end_call: End the call." in out
    assert "- transfer_to_ingroup: Transfer to a human agent." in out


def test_disclosure_response_present():
    out = build_system_prompt(_basic_ctx())
    assert "AI assistant" in out


def test_missing_persona_fields_render_safely():
    # ChainableUndefined + default filter means missing keys give defaults,
    # not crashes.
    ctx = PromptContext(
        persona={},
        lead={},
        campaign={},
        script={},
        tools=[],
    )
    out = build_system_prompt(ctx)
    assert "an AI assistant" in out
    assert "the customer" in out


def test_kb_block_only_appears_when_enabled():
    out_off = build_system_prompt(_basic_ctx(kb_enabled=False))
    out_on = build_system_prompt(_basic_ctx(kb_enabled=True))
    assert "KNOWLEDGE BASE" not in out_off
    assert "KNOWLEDGE BASE" in out_on


def test_custom_template_overrides_default():
    out = build_system_prompt(
        _basic_ctx(),
        template_str="ROLE: {{ persona.name }}",
    )
    assert out == "ROLE: Sam"
