# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Integration test: examples/plugins/banking_demo/ round-trips through
plugin_loader -> ruflo_compat -> ToolDef and the handlers actually run.

This is the smoke test for the entire ruflo synthesis path. If this
passes, dropping any conformant ruflo manifest into the plugins
directory works in the same way.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lub.mcp.schemas import (  # noqa: F401 — imported for symmetry with other test files
    EstimatorInput,
    MetricInput,
)
from lub.mcp.tools.plugin_loader import discover_ruflo_plugins
from lub.mcp.tools.ruflo_compat import RufloPluginInput, RufloPluginOutput

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES_PLUGINS = _REPO_ROOT / "examples" / "plugins"


@pytest.fixture(scope="module")
def banking_demo_tools() -> list:
    if not (_EXAMPLES_PLUGINS / "banking_demo").is_dir():
        pytest.skip("examples/plugins/banking_demo/ not present in repo checkout")
    return discover_ruflo_plugins(_EXAMPLES_PLUGINS)


def test_banking_demo_loads_two_tools(banking_demo_tools: list) -> None:
    names = {t.name for t in banking_demo_tools}
    assert names == {
        "ruflo.banking-demo.sr_11_7_check",
        "ruflo.banking-demo.regime_lookup",
    }


def test_sr_11_7_check_flags_uncalibrated_claim(banking_demo_tools: list) -> None:
    tool = next(
        t for t in banking_demo_tools if t.name == "ruflo.banking-demo.sr_11_7_check"
    )
    payload = RufloPluginInput(
        args={"claim": "Our model achieves 95% accuracy on test data."}
    ).model_dump()
    out = tool.handler(payload)
    parsed = RufloPluginOutput.model_validate(out)
    assert parsed.tool == "sr_11_7_check"
    assert parsed.result["verdict"] == "uncalibrated_claim"
    assert "SR 11-7" in parsed.result["rationale"]


def test_sr_11_7_check_passes_when_calibrated_metric_cited(
    banking_demo_tools: list,
) -> None:
    tool = next(
        t for t in banking_demo_tools if t.name == "ruflo.banking-demo.sr_11_7_check"
    )
    payload = RufloPluginInput(
        args={"claim": "Model achieves ECE of 0.04 and Brier score 0.12."}
    ).model_dump()
    out = tool.handler(payload)
    parsed = RufloPluginOutput.model_validate(out)
    assert parsed.result["verdict"] == "passes"
    assert "ece" in parsed.result["matched_terms"]
    assert "brier" in parsed.result["matched_terms"]


def test_regime_lookup_returns_canonical_title_for_known_regime(
    banking_demo_tools: list,
) -> None:
    tool = next(
        t for t in banking_demo_tools if t.name == "ruflo.banking-demo.regime_lookup"
    )
    for short, expected_enum in [
        ("nist", "NIST_GENAI"),
        ("eu", "EU_AI_ACT"),
        ("bcbs", "BCBS"),
        ("bcb", "BCB"),
        ("iso23894", "ISO_23894"),
        ("iso42001", "ISO_42001"),
    ]:
        payload = RufloPluginInput(args={"regime": short}).model_dump()
        out = tool.handler(payload)
        parsed = RufloPluginOutput.model_validate(out)
        assert parsed.result["found"] is True
        assert parsed.result["enum"] == expected_enum
        assert parsed.result["title"]


def test_regime_lookup_reports_unknown_regime_with_valid_keys(
    banking_demo_tools: list,
) -> None:
    tool = next(
        t for t in banking_demo_tools if t.name == "ruflo.banking-demo.regime_lookup"
    )
    payload = RufloPluginInput(args={"regime": "fdic"}).model_dump()
    out = tool.handler(payload)
    parsed = RufloPluginOutput.model_validate(out)
    assert parsed.result["found"] is False
    assert parsed.result["input"] == "fdic"
    assert "nist" in parsed.result["valid_keys"]
    assert "iso42001" in parsed.result["valid_keys"]


def test_banking_demo_tools_use_uniform_output_schema(
    banking_demo_tools: list,
) -> None:
    """Every plugin tool emits a RufloPluginOutput regardless of contents."""
    for tool in banking_demo_tools:
        assert tool.output_model is RufloPluginOutput
