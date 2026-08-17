# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for the OCC 2011-12 findings/observations taxonomy."""

from __future__ import annotations

from lub.reports.findings import (
    DEFAULT_THRESHOLDS,
    FindingClassifier,
    MetricThreshold,
    Report,
    Severity,
)
from tests import make_benchmark_result

_BASE_METRICS: dict[str, float] = dict(make_benchmark_result().metrics)


# ---- MetricThreshold -------------------------------------------------------


def test_higher_is_better_pass() -> None:
    th = MetricThreshold(observation=0.70, finding=0.50, higher_is_better=True)
    assert th.classify(0.80) is Severity.PASS


def test_higher_is_better_observation() -> None:
    th = MetricThreshold(observation=0.70, finding=0.50, higher_is_better=True)
    assert th.classify(0.60) is Severity.OBSERVATION


def test_higher_is_better_finding() -> None:
    th = MetricThreshold(observation=0.70, finding=0.50, higher_is_better=True)
    assert th.classify(0.40) is Severity.FINDING


def test_lower_is_better_pass() -> None:
    th = MetricThreshold(observation=0.05, finding=0.10, higher_is_better=False)
    assert th.classify(0.03) is Severity.PASS


def test_lower_is_better_observation() -> None:
    th = MetricThreshold(observation=0.05, finding=0.10, higher_is_better=False)
    assert th.classify(0.07) is Severity.OBSERVATION


def test_lower_is_better_finding() -> None:
    th = MetricThreshold(observation=0.05, finding=0.10, higher_is_better=False)
    assert th.classify(0.15) is Severity.FINDING


# ---- FindingClassifier -----------------------------------------------------


def test_classifier_labels_all_metrics() -> None:
    record = make_benchmark_result()
    report = FindingClassifier().classify(record)
    assert isinstance(report, Report)
    assert len(report.classified) == len(record.metrics)


def test_classifier_detects_finding_on_bad_ece() -> None:
    record = make_benchmark_result(metrics={**_BASE_METRICS, "ece": 0.20})
    report = FindingClassifier().classify(record)
    ece_row = next(m for m in report.classified if m.name == "ece")
    assert ece_row.severity is Severity.FINDING


def test_classifier_passes_good_metrics() -> None:
    record = make_benchmark_result(metrics={**_BASE_METRICS, "ece": 0.03, "accuracy": 0.90, "refusal_auroc": 0.85})
    report = FindingClassifier().classify(record)
    for m in report.classified:
        if m.name in ("ece", "accuracy", "refusal_auroc"):
            assert m.severity is Severity.PASS, f"{m.name} should PASS"


def test_report_worst_is_finding_when_any_finding() -> None:
    record = make_benchmark_result(metrics={**_BASE_METRICS, "ece": 0.20})
    report = FindingClassifier().classify(record)
    assert report.worst is Severity.FINDING


def test_report_worst_is_pass_when_all_clean() -> None:
    record = make_benchmark_result(metrics={**_BASE_METRICS, "ece": 0.03, "accuracy": 0.90, "refusal_auroc": 0.85, "brier": 0.10})
    report = FindingClassifier().classify(record)
    assert report.worst is Severity.PASS


def test_custom_thresholds_override_defaults() -> None:
    strict = {"ece": MetricThreshold(observation=0.01, finding=0.02, higher_is_better=False)}
    record = make_benchmark_result(metrics={**_BASE_METRICS, "ece": 0.015})
    report = FindingClassifier(thresholds=strict).classify(record)
    ece_row = next(m for m in report.classified if m.name == "ece")
    assert ece_row.severity is Severity.OBSERVATION


def test_default_thresholds_cover_core_metrics() -> None:
    for key in ("accuracy", "ece", "refusal_auroc", "brier", "prr"):
        assert key in DEFAULT_THRESHOLDS, f"missing threshold for {key}"
