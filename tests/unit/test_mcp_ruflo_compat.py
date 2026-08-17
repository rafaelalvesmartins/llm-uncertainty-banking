# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for lub.mcp.tools.ruflo_compat — manifest -> ToolDef shim."""

from __future__ import annotations

from typing import Any

import pytest

from lub.mcp.tools.ruflo_compat import (
    RufloPluginInput,
    RufloPluginOutput,
    adapt_ruflo_manifest,
)

_SAMPLE_MANIFEST: dict[str, Any] = {
    "name": "@claude-flow/plugin-banking-compliance",
    "version": "0.1.0",
    "description": "Calibrated agents for SR 11-7 / Basel III / BCB 4658",
    "tools": [
        {
            "name": "sr_11_7_audit",
            "description": "Audit a model-risk questionnaire against SR 11-7.",
        },
        {
            "name": "basel_pillar3_draft",
            "description": "Draft a Basel III Pillar 3 disclosure section.",
            "input_schema": {"type": "object", "properties": {"section": {"type": "string"}}},
        },
    ],
}


def _h_audit(args: dict[str, Any]) -> dict[str, Any]:
    return {"verdict": "uncalibrated_claim", "input_seen": list(args.keys())}


def _h_basel(args: dict[str, Any]) -> dict[str, Any]:
    return {"draft": f"Pillar 3 draft for section={args.get('section', '?')}"}


def test_adapt_returns_one_tooldef_per_manifest_tool() -> None:
    tools = adapt_ruflo_manifest(
        _SAMPLE_MANIFEST,
        handlers={"sr_11_7_audit": _h_audit, "basel_pillar3_draft": _h_basel},
    )
    assert len(tools) == 2


def test_tool_names_are_namespaced_under_ruflo_prefix() -> None:
    tools = adapt_ruflo_manifest(
        _SAMPLE_MANIFEST,
        handlers={"sr_11_7_audit": _h_audit, "basel_pillar3_draft": _h_basel},
    )
    names = {t.name for t in tools}
    assert names == {
        "ruflo.banking-compliance.sr_11_7_audit",
        "ruflo.banking-compliance.basel_pillar3_draft",
    }


def test_handler_round_trip_uses_uniform_output_schema() -> None:
    tools = adapt_ruflo_manifest(
        _SAMPLE_MANIFEST,
        handlers={"sr_11_7_audit": _h_audit, "basel_pillar3_draft": _h_basel},
    )
    audit = next(t for t in tools if t.name.endswith("sr_11_7_audit"))
    payload = RufloPluginInput(args={"questionnaire_id": "Q-2026-04"}).model_dump()
    out = audit.handler(payload)
    parsed = RufloPluginOutput.model_validate(out)
    assert parsed.plugin == "@claude-flow/plugin-banking-compliance"
    assert parsed.tool == "sr_11_7_audit"
    assert parsed.result["verdict"] == "uncalibrated_claim"


def test_input_schema_passthrough_uses_args_dict() -> None:
    tools = adapt_ruflo_manifest(
        _SAMPLE_MANIFEST,
        handlers={"sr_11_7_audit": _h_audit, "basel_pillar3_draft": _h_basel},
    )
    basel = next(t for t in tools if t.name.endswith("basel_pillar3_draft"))
    # Even though basel had its own input_schema, the passthrough still
    # accepts an `args` dict.
    out = basel.handler({"args": {"section": "credit_risk"}})
    parsed = RufloPluginOutput.model_validate(out)
    assert "credit_risk" in parsed.result["draft"]


def test_missing_handler_raises_at_adapt_time() -> None:
    with pytest.raises(KeyError, match="basel_pillar3_draft"):
        adapt_ruflo_manifest(
            _SAMPLE_MANIFEST,
            handlers={"sr_11_7_audit": _h_audit},  # missing basel handler
        )


def test_invalid_manifest_missing_name() -> None:
    with pytest.raises(ValueError, match="missing 'name'"):
        adapt_ruflo_manifest({"tools": []}, handlers={})


def test_invalid_manifest_tools_not_list() -> None:
    with pytest.raises(ValueError, match="must be a list"):
        adapt_ruflo_manifest(
            {"name": "@claude-flow/plugin-x", "tools": "not-a-list"}, handlers={}
        )


def test_short_plugin_name_strips_claude_flow_prefix() -> None:
    manifest = {
        "name": "@claude-flow/plugin-foo",
        "tools": [{"name": "bar", "description": "x"}],
    }
    tools = adapt_ruflo_manifest(manifest, handlers={"bar": lambda _a: {"ok": True}})
    assert tools[0].name == "ruflo.foo.bar"


def test_non_namespaced_plugin_name_passes_through() -> None:
    manifest = {
        "name": "ruflo-banking-pack",  # no @claude-flow/ prefix
        "tools": [{"name": "ping", "description": "x"}],
    }
    tools = adapt_ruflo_manifest(manifest, handlers={"ping": lambda _a: {"ok": True}})
    assert tools[0].name == "ruflo.ruflo-banking-pack.ping"
