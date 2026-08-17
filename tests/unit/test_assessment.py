# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for the OSCAL Assessment-Results generator."""

from __future__ import annotations

import json

from lub.reports.assessment import (
    OscalAssessmentResults,
    build_assessment_results,
    render_assessment_json,
)
from lub.reports.crosswalk import Regime
from lub.types import BenchmarkResult
from tests import make_benchmark_result


def test_build_returns_assessment_results() -> None:
    ar = build_assessment_results(make_benchmark_result())
    assert isinstance(ar, OscalAssessmentResults)


def test_assessment_has_uuid_and_metadata() -> None:
    ar = build_assessment_results(make_benchmark_result())
    assert ar.uuid
    assert ar.metadata.title
    assert ar.metadata.oscal_version == "1.1.2"


def test_assessment_has_results_with_observations() -> None:
    ar = build_assessment_results(make_benchmark_result())
    assert len(ar.results) == 1
    result = ar.results[0]
    assert len(result.observations) >= 1


def test_assessment_has_results_with_findings() -> None:
    ar = build_assessment_results(make_benchmark_result())
    result = ar.results[0]
    assert len(result.findings) >= 1


def test_render_produces_valid_json() -> None:
    text = render_assessment_json(make_benchmark_result())
    parsed = json.loads(text)
    assert "assessment-results" in parsed
    ar = parsed["assessment-results"]
    assert "uuid" in ar
    assert "metadata" in ar
    assert "results" in ar


def test_observations_carry_metric_evidence() -> None:
    text = render_assessment_json(make_benchmark_result())
    parsed = json.loads(text)
    observations = parsed["assessment-results"]["results"][0]["observations"]
    assert len(observations) >= 1
    # Check that observations have relevant-evidence with props
    for obs in observations:
        assert obs["methods"] == ["TEST"]
        assert len(obs["relevant-evidence"]) >= 1
        ev = obs["relevant-evidence"][0]
        prop_names = {p["name"] for p in ev["props"]}
        assert "metric" in prop_names
        assert "value" in prop_names
        assert "severity" in prop_names
        assert "regime" in prop_names


def test_findings_reference_observations() -> None:
    text = render_assessment_json(make_benchmark_result())
    parsed = json.loads(text)
    result = parsed["assessment-results"]["results"][0]
    findings = result["findings"]
    observations = result["observations"]
    obs_uuids = {o["uuid"] for o in observations}
    for finding in findings:
        for ro in finding["related-observations"]:
            assert ro["observation-uuid"] in obs_uuids


def test_finding_status_reflects_severity() -> None:
    # ECE=0.20 should trigger a FINDING
    record = make_benchmark_result()
    record_dict = record.model_dump()
    record_dict["ece"] = 0.20
    record_dict["metrics"]["ece"] = 0.20
    record = BenchmarkResult(**record_dict)
    text = render_assessment_json(record)
    parsed = json.loads(text)
    findings = parsed["assessment-results"]["results"][0]["findings"]
    statuses = [f["target"]["status"]["state"] for f in findings]
    assert "not-satisfied" in statuses


def test_regime_filter_limits_output() -> None:
    ar_all = build_assessment_results(make_benchmark_result())
    ar_one = build_assessment_results(
        make_benchmark_result(), regime_filter={Regime.NIST_GENAI}
    )
    n_all = len(ar_all.results[0].observations)
    n_one = len(ar_one.results[0].observations)
    assert n_one < n_all


def test_custom_title_propagates() -> None:
    ar = build_assessment_results(make_benchmark_result(), title="Custom Assessment")
    assert ar.metadata.title == "Custom Assessment"


def test_multi_regime_observations_have_regime_prop() -> None:
    text = render_assessment_json(make_benchmark_result())
    parsed = json.loads(text)
    observations = parsed["assessment-results"]["results"][0]["observations"]
    regime_values = set()
    for obs in observations:
        for p in obs["props"]:
            if p["name"] == "regime":
                regime_values.add(p["value"])
    # Should have observations across multiple regimes
    assert len(regime_values) >= 3


def test_result_props_include_summary() -> None:
    text = render_assessment_json(make_benchmark_result())
    parsed = json.loads(text)
    result = parsed["assessment-results"]["results"][0]
    prop_names = {p["name"] for p in result["props"]}
    assert "n_observations" in prop_names
    assert "n_findings" in prop_names
    assert "worst_severity" in prop_names
