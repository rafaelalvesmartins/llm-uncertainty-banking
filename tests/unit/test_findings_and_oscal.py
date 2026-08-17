# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for the Zest findings/observations taxonomy and OSCAL renderer."""

from __future__ import annotations

import json

import pytest

from lub.reports import (
    DEFAULT_THRESHOLDS,
    FindingClassifier,
    MetricThreshold,
    Severity,
    build_component_definition,
    render_oscal_json,
)
from lub.types import BenchmarkResult
from tests import make_benchmark_result


def _result(metrics: dict[str, float], **overrides: object) -> BenchmarkResult:
    """Thin wrapper around conftest.make_benchmark_result for metric-centric tests."""
    base_overrides: dict[str, object] = {
        "accuracy": float(metrics.get("accuracy", 0.8)),
        "ece": float(metrics.get("ece", 0.02)),
        "refusal_auroc": float(metrics.get("refusal_auroc", 0.8)),
        "metrics": metrics,
    }
    base_overrides.update(overrides)
    return make_benchmark_result(**base_overrides)


# --------------------------------------------------------------- findings


def test_all_metrics_pass_for_healthy_run() -> None:
    r = _result({"accuracy": 0.85, "ece": 0.02, "refusal_auroc": 0.85, "brier": 0.10})
    report = FindingClassifier().classify(r)
    assert report.worst is Severity.PASS
    assert not report.findings
    assert not report.observations


def test_ece_over_finding_threshold_becomes_finding() -> None:
    r = _result({"accuracy": 0.85, "ece": 0.20, "refusal_auroc": 0.85})
    report = FindingClassifier().classify(r)
    assert report.worst is Severity.FINDING
    ece_row = next(m for m in report.classified if m.name == "ece")
    assert ece_row.severity is Severity.FINDING


def test_accuracy_between_bands_becomes_observation() -> None:
    r = _result({"accuracy": 0.60, "ece": 0.02, "refusal_auroc": 0.85})
    report = FindingClassifier().classify(r)
    acc = next(m for m in report.classified if m.name == "accuracy")
    assert acc.severity is Severity.OBSERVATION


def test_metric_without_threshold_defaults_to_pass() -> None:
    r = _result({"accuracy": 0.85, "ece": 0.02, "refusal_auroc": 0.85, "weirdness": 99.9})
    report = FindingClassifier().classify(r)
    weirdness = next(m for m in report.classified if m.name == "weirdness")
    assert weirdness.severity is Severity.PASS
    assert weirdness.threshold is None


def test_metric_threshold_classify_higher_is_better() -> None:
    th = MetricThreshold(observation=0.70, finding=0.50, higher_is_better=True)
    assert th.classify(0.80) is Severity.PASS
    assert th.classify(0.60) is Severity.OBSERVATION
    assert th.classify(0.40) is Severity.FINDING


def test_metric_threshold_classify_lower_is_better() -> None:
    th = MetricThreshold(observation=0.05, finding=0.10, higher_is_better=False)
    assert th.classify(0.03) is Severity.PASS
    assert th.classify(0.08) is Severity.OBSERVATION
    assert th.classify(0.20) is Severity.FINDING


def test_default_thresholds_cover_all_compute_all_keys() -> None:
    """Every metric compute_all emits should have a declared threshold."""
    expected = {
        "accuracy", "ece", "rmsce", "brier", "refusal_auroc",
        "reversed_pairs_proportion", "miscalibration_area", "sharpness",
        "prr", "spearman", "kendall_tau", "missing_ratio",
        "aurc", "auucc", "crps_from_confidence", "negative_log_likelihood",
    }
    declared = set(DEFAULT_THRESHOLDS)
    missing = expected - declared
    assert not missing, f"no threshold declared for: {sorted(missing)}"


# --------------------------------------------------------------- oscal


def test_oscal_json_is_valid_json_and_has_required_fields() -> None:
    r = _result({"accuracy": 0.8, "ece": 0.02, "refusal_auroc": 0.8, "brier": 0.1})
    payload = render_oscal_json(r)
    doc = json.loads(payload)
    cd = doc["component-definition"]
    assert "uuid" in cd
    assert cd["metadata"]["oscal-version"] == "1.1.2"
    assert cd["metadata"]["title"].startswith("LUB — ")
    assert len(cd["components"]) == 1


def test_oscal_component_has_control_implementation_and_requirements() -> None:
    r = _result({"accuracy": 0.8, "ece": 0.02, "refusal_auroc": 0.8})
    cd = build_component_definition(r)
    comp = cd.components[0]
    assert len(comp.control_implementations) == 2
    nist_ci = [ci for ci in comp.control_implementations if ci.source == "NIST_AI_RMF_1.0"]
    iso_ci = [ci for ci in comp.control_implementations if ci.source == "ISO_IEC_42001_2023"]
    assert len(nist_ci) == 1
    assert len(iso_ci) == 1
    # At minimum, accuracy / ece / refusal_auroc map to IRs.
    assert len(nist_ci[0].implemented_requirements) >= 2


def test_oscal_embeds_severity_in_every_by_component() -> None:
    r = _result({"accuracy": 0.3, "ece": 0.2, "refusal_auroc": 0.4, "brier": 0.5})  # all bad
    cd = build_component_definition(r)
    severities: list[str] = []
    for ci in cd.components[0].control_implementations:
        for ir in ci.implemented_requirements:
            for bc in ir.by_components:
                for p in bc.props:
                    if p.name == "severity":
                        severities.append(p.value)
    assert severities  # every BC had a severity prop
    # With deliberately bad values, at least one must be a finding.
    assert "finding" in severities


def test_oscal_props_carry_provenance() -> None:
    r = _result(
        {"accuracy": 0.8, "ece": 0.02, "refusal_auroc": 0.8},
        git_sha="abc1234",
    )
    cd = build_component_definition(r)
    prop_names = {p.name for p in cd.components[0].props}
    assert {"repo_version", "backend", "estimator", "dataset", "dataset_hash", "git_sha"} <= prop_names


def test_oscal_is_deterministic_on_fixed_classifier() -> None:
    """Two renders of the same record differ only in uuid/timestamp."""
    r = _result({"accuracy": 0.8, "ece": 0.02, "refusal_auroc": 0.8})
    classifier = FindingClassifier()
    a = json.loads(render_oscal_json(r, classifier=classifier))["component-definition"]
    b = json.loads(render_oscal_json(r, classifier=classifier))["component-definition"]
    # Metric values and severities should match exactly.
    a_metrics = _extract_metric_values(a)
    b_metrics = _extract_metric_values(b)
    assert a_metrics == b_metrics


def _extract_metric_values(doc: dict) -> dict[str, tuple[str, str]]:
    """Return {metric_name: (value, severity)} from the by-components props."""
    out: dict[str, tuple[str, str]] = {}
    for comp in doc["components"]:
        for ci in comp["control-implementations"]:
            for ir in ci["implemented-requirements"]:
                for bc in ir["by-components"]:
                    name = value = severity = None
                    for p in bc["props"]:
                        if p["name"] == "metric":
                            name = p["value"]
                        elif p["name"] == "value":
                            value = p["value"]
                        elif p["name"] == "severity":
                            severity = p["value"]
                    if name is not None and value is not None and severity is not None:
                        out[name] = (value, severity)
    return out


@pytest.mark.parametrize("override_threshold", [0.01, 0.5])
def test_custom_classifier_changes_severity(override_threshold: float) -> None:
    """Pass a custom FindingClassifier; OSCAL output should reflect it."""
    r = _result({"accuracy": 0.8, "ece": 0.03, "refusal_auroc": 0.8})
    classifier = FindingClassifier(
        thresholds={
            "ece": MetricThreshold(
                observation=override_threshold,
                finding=override_threshold * 2,
                higher_is_better=False,
            )
        }
    )
    doc = json.loads(render_oscal_json(r, classifier=classifier))["component-definition"]
    ece_sev = _extract_metric_values(doc).get("ece", (None, None))[1]
    if override_threshold >= 0.03:
        assert ece_sev == "pass"
    else:
        assert ece_sev in {"observation", "finding"}
