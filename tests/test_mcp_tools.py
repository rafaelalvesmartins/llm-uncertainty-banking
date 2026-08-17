# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the auto-generated MCP tool surface.

Coverage targets:
* the auto-discovery walks every public estimator (minus the documented
  skip list) and produces a ToolDef with the expected name/schema shape;
* every metric in :data:`_METRIC_SPECS` produces a ToolDef;
* representative handlers actually compute end-to-end against
  DummyBackend / synthetic confidence-correctness arrays without raising
  and produce schema-valid output.
"""

from __future__ import annotations

import pytest

from lub.mcp.schemas import EstimatorInput, EstimatorOutput, MetricInput, MetricOutput
from lub.mcp.server import list_all_tools
from lub.mcp.tools import build_auto_tools
from lub.mcp.tools.estimators import _SKIP, build_estimator_tools
from lub.mcp.tools.metrics import _METRIC_SPECS, build_metric_tools

# ---------------------------------------------------------------------------
# Discovery / shape
# ---------------------------------------------------------------------------


def test_estimator_tools_built_for_every_non_skipped_class() -> None:
    from lub import uncertainty

    tools = build_estimator_tools()
    discovered_keys = {t.name for t in tools}
    expected = {
        f"lub.estimator.{getattr(getattr(uncertainty, n), 'REGISTRY_KEY', '')}"
        for n in uncertainty.__all__
        if n != "Estimator" and n not in _SKIP
    }
    expected.discard("lub.estimator.")  # any without a REGISTRY_KEY
    assert discovered_keys == expected


def test_metric_tools_built_one_per_spec() -> None:
    tools = build_metric_tools()
    assert len(tools) == len(_METRIC_SPECS)
    expected = {f"lub.metric.{name}" for name, _, _ in _METRIC_SPECS}
    assert {t.name for t in tools} == expected


def test_estimator_tool_uses_shared_schemas() -> None:
    tools = build_estimator_tools()
    assert tools, "expected at least one estimator tool"
    assert all(t.input_model is EstimatorInput for t in tools)
    assert all(t.output_model is EstimatorOutput for t in tools)


def test_metric_tool_uses_shared_schemas() -> None:
    tools = build_metric_tools()
    assert tools, "expected at least one metric tool"
    assert all(t.input_model is MetricInput for t in tools)
    assert all(t.output_model is MetricOutput for t in tools)


def test_build_auto_tools_concatenates_estimators_then_metrics() -> None:
    auto = build_auto_tools()
    n_est = len(build_estimator_tools())
    n_met = len(build_metric_tools())
    # Auto-tools are: estimators, then metrics, then CEC tools (4),
    # then any discovered ruflo plugins. We assert the prefix shape
    # rather than an exact total because the plugin discovery and the
    # CEC catalog are both feature-gated extensions.
    assert len(auto) >= n_est + n_met
    assert all(t.name.startswith("lub.estimator.") for t in auto[:n_est])
    assert all(t.name.startswith("lub.metric.") for t in auto[n_est : n_est + n_met])


def test_list_all_tools_includes_workflow_and_auto() -> None:
    catalog = list_all_tools()
    names = {t.name for t in catalog}
    # workflow tools (hand-written)
    assert "score_with_p_true" in names
    assert "airmf_report" in names
    assert "cascaded_answer" in names
    # auto-generated samples
    assert "lub.estimator.token_logprob" in names
    assert "lub.metric.brier" in names


# ---------------------------------------------------------------------------
# Smoke runs — handlers actually execute
# ---------------------------------------------------------------------------


def test_estimator_handler_token_logprob_smoke() -> None:
    tool = next(t for t in build_estimator_tools() if t.name == "lub.estimator.token_logprob")
    payload = EstimatorInput(prompt="What is 2+2?").model_dump()
    out = tool.handler(payload)
    parsed = EstimatorOutput.model_validate(out)
    assert parsed.estimator == "token_logprob"
    assert 0.0 <= parsed.confidence <= 1.0
    assert isinstance(parsed.answer, str)


def test_estimator_handler_self_consistency_smoke() -> None:
    tool = next(
        t for t in build_estimator_tools() if t.name == "lub.estimator.self_consistency"
    )
    payload = EstimatorInput(
        prompt="Pick a number 1-10.", estimator_kwargs={"n_samples": 3}
    ).model_dump()
    out = tool.handler(payload)
    parsed = EstimatorOutput.model_validate(out)
    assert parsed.estimator == "self_consistency"
    assert 0.0 <= parsed.confidence <= 1.0


@pytest.mark.parametrize(
    "metric_name,confs,correct,expected_finite",
    [
        ("brier", [0.9, 0.1, 0.6], [1.0, 0.0, 1.0], True),
        ("ece", [0.9, 0.1, 0.6, 0.55], [1.0, 0.0, 1.0, 0.0], True),
        ("refusal_auroc", [0.2, 0.8, 0.6, 0.4], [0.0, 1.0, 1.0, 0.0], True),
        ("sharpness", [0.1, 0.5, 0.9], [1.0, 0.0, 1.0], True),
    ],
)
def test_metric_handler_smoke(
    metric_name: str,
    confs: list[float],
    correct: list[float],
    expected_finite: bool,
) -> None:
    tool = next(t for t in build_metric_tools() if t.name == f"lub.metric.{metric_name}")
    payload = MetricInput(confidences=confs, correct=correct).model_dump()
    out = tool.handler(payload)
    parsed = MetricOutput.model_validate(out)
    assert parsed.metric == metric_name
    if expected_finite:
        import math

        assert math.isfinite(parsed.value)


# ---------------------------------------------------------------------------
# Catalog hygiene
# ---------------------------------------------------------------------------


def test_no_duplicate_tool_names_in_full_catalog() -> None:
    names = [t.name for t in list_all_tools()]
    assert len(names) == len(set(names)), "tool names must be unique across all flows"
