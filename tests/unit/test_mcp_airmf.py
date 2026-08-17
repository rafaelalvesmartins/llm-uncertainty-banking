# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the MCP airmf_report handler.

The handler goes through the real :class:`~lub.reports.renderer.AIRMFReporter`
— this test ensures the pydantic input / output contract stays compatible
with that renderer (i.e. no schema drift between the MCP surface and the
underlying report templates).
"""

from __future__ import annotations

import pytest

from lub.mcp.server import TOOLS, AirmfInput, AirmfOutput, _handle_airmf_report


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "backend": "dummy",
        "estimator": "token_logprob",
        "dataset": "br_regulatory",
        "dataset_version": "test",
        "n": 10,
        "accuracy": 0.7,
        "ece": 0.08,
        "refusal_auroc": 0.82,
        "metrics": {"brier": 0.18},
    }
    base.update(overrides)
    return base


def test_airmf_input_enforces_format_values() -> None:
    with pytest.raises(ValueError):
        AirmfInput.model_validate({**_payload(), "format": "pdf"})


def test_airmf_input_accepts_md_default() -> None:
    parsed = AirmfInput.model_validate(_payload())
    assert parsed.format == "md"
    assert parsed.metrics == {"brier": 0.18}


def test_airmf_report_renders_markdown() -> None:
    out = _handle_airmf_report(_payload())
    parsed = AirmfOutput.model_validate(out)
    assert parsed.format == "md"
    assert parsed.body  # non-empty body
    assert parsed.n_findings >= 0
    # Markdown should mention AI RMF in the title or body
    assert "AI" in parsed.body or "RMF" in parsed.body or "rmf" in parsed.body.lower()


def test_airmf_report_renders_html_when_requested() -> None:
    out = _handle_airmf_report(_payload(format="html"))
    parsed = AirmfOutput.model_validate(out)
    assert parsed.format == "html"
    assert "<html" in parsed.body.lower() or "<body" in parsed.body.lower()


def test_airmf_tool_is_registered() -> None:
    names = {tool.name for tool in TOOLS}
    assert "airmf_report" in names
    airmf = next(t for t in TOOLS if t.name == "airmf_report")
    assert airmf.input_model is AirmfInput
    assert airmf.output_model is AirmfOutput
