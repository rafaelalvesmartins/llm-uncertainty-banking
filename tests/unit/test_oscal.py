# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for the OSCAL Component Definition output."""

from __future__ import annotations

import json

from lub.reports.oscal import (
    OscalComponentDefinition,
    build_component_definition,
    render_oscal_json,
)
from lub.types import BenchmarkResult
from tests import make_benchmark_result


def test_build_returns_oscal_component_definition() -> None:
    cd = build_component_definition(make_benchmark_result())
    assert isinstance(cd, OscalComponentDefinition)


def test_render_produces_valid_json() -> None:
    text = render_oscal_json(make_benchmark_result())
    parsed = json.loads(text)
    assert "component-definition" in parsed
    cd = parsed["component-definition"]
    assert "uuid" in cd
    assert "metadata" in cd
    assert "components" in cd
    assert len(cd["components"]) == 1


def test_component_carries_backend_and_estimator() -> None:
    text = render_oscal_json(make_benchmark_result())
    parsed = json.loads(text)
    comp = parsed["component-definition"]["components"][0]
    assert "DummyBackend" in comp["title"] or "token_logprob" in comp["title"]
    assert comp["type"] == "software"


def test_implemented_requirements_reference_ai_rmf() -> None:
    text = render_oscal_json(make_benchmark_result())
    parsed = json.loads(text)
    comp = parsed["component-definition"]["components"][0]
    ci = comp["control-implementations"]
    assert len(ci) >= 1
    irs = ci[0]["implemented-requirements"]
    assert len(irs) >= 1
    control_ids = {ir["control-id"] for ir in irs}
    assert any("measure" in cid.lower() for cid in control_ids)


def test_by_components_carry_metric_props() -> None:
    text = render_oscal_json(make_benchmark_result())
    parsed = json.loads(text)
    comp = parsed["component-definition"]["components"][0]
    irs = comp["control-implementations"][0]["implemented-requirements"]
    all_bcs = [bc for ir in irs for bc in ir.get("by-components", [])]
    assert len(all_bcs) >= 1
    prop_names = {p["name"] for bc in all_bcs for p in bc.get("props", [])}
    assert "metric" in prop_names
    assert "value" in prop_names
    assert "severity" in prop_names
    assert "trust_dimension" in prop_names


def test_severity_labels_appear_in_descriptions() -> None:
    record = make_benchmark_result(ece=0.20)
    record_dict = record.model_dump()
    record_dict["metrics"]["ece"] = 0.20
    record = BenchmarkResult(**record_dict)
    text = render_oscal_json(record)
    assert "FINDING" in text or "finding" in text


def test_custom_title_propagates() -> None:
    cd = build_component_definition(make_benchmark_result(), title="Custom Title")
    text = cd.model_dump_json(by_alias=True, indent=2)
    assert "Custom Title" in text
