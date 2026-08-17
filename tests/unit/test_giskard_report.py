# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for reports/giskard_report.py — vulnerability scanner companion."""

from __future__ import annotations

from lub.reports.giskard_report import (
    IssueCategory,
    IssueSeverity,
    VulnerabilityIssue,
    VulnerabilityReport,
    scan_benchmark_result,
)
from lub.types import BenchmarkResult
from tests import make_benchmark_result


def test_scan_healthy_result_passes() -> None:
    report = scan_benchmark_result(make_benchmark_result())
    assert report.passed
    assert report.worst_severity in (IssueSeverity.INFO, IssueSeverity.MINOR, IssueSeverity.MEDIUM)


def test_scan_high_ece_triggers_issue() -> None:
    r = make_benchmark_result(ece=0.20)
    d = r.model_dump()
    d["metrics"]["ece"] = 0.20
    report = scan_benchmark_result(BenchmarkResult(**d))
    ece_issues = [i for i in report.issues if i.metric_name == "ece"]
    assert len(ece_issues) >= 1
    assert any(i.category == IssueCategory.CALIBRATION for i in ece_issues)


def test_scan_low_auroc_triggers_critical() -> None:
    r = make_benchmark_result(refusal_auroc=0.55)
    d = r.model_dump()
    d["metrics"]["refusal_auroc"] = 0.55
    report = scan_benchmark_result(BenchmarkResult(**d))
    auroc_issues = [i for i in report.issues if i.metric_name == "refusal_auroc"]
    assert len(auroc_issues) >= 1
    assert any(i.severity == IssueSeverity.CRITICAL for i in auroc_issues)
    assert not report.passed


def test_scan_low_accuracy_triggers_critical() -> None:
    r = make_benchmark_result(accuracy=0.40)
    d = r.model_dump()
    d["metrics"]["accuracy"] = 0.40
    report = scan_benchmark_result(BenchmarkResult(**d))
    acc_issues = [i for i in report.issues if i.metric_name == "accuracy"]
    assert any(i.severity == IssueSeverity.CRITICAL for i in acc_issues)


def test_scan_high_missing_ratio_triggers_major() -> None:
    r = make_benchmark_result(missing_ratio=0.50)
    d = r.model_dump()
    d["metrics"]["missing_ratio"] = 0.50
    report = scan_benchmark_result(BenchmarkResult(**d))
    mr_issues = [i for i in report.issues if i.metric_name == "missing_ratio"]
    assert any(i.severity == IssueSeverity.MAJOR for i in mr_issues)


def test_vulnerability_report_to_dict() -> None:
    report = scan_benchmark_result(make_benchmark_result())
    d = report.to_dict()
    assert "timestamp" in d
    assert "backend" in d
    assert "passed" in d
    assert isinstance(d["issues"], list)


def test_vulnerability_report_worst_severity_no_issues() -> None:
    report = VulnerabilityReport(
        timestamp="2026-01-01", backend="x", estimator="y", dataset="z"
    )
    assert report.worst_severity == IssueSeverity.INFO
    assert report.passed


def test_vulnerability_issue_frozen() -> None:
    issue = VulnerabilityIssue(
        category=IssueCategory.HALLUCINATION,
        severity=IssueSeverity.MAJOR,
        description="test",
        metric_name="accuracy",
        metric_value=0.4,
        threshold=0.5,
    )
    assert issue.category == IssueCategory.HALLUCINATION


def test_scan_rejects_non_benchmark_result() -> None:
    import pytest
    with pytest.raises(TypeError, match="BenchmarkResult"):
        scan_benchmark_result({"not": "a result"})  # type: ignore[arg-type]


def test_multiple_issues_worst_severity() -> None:
    r = make_benchmark_result(accuracy=0.40, ece=0.20, refusal_auroc=0.55)
    d = r.model_dump()
    d["metrics"]["accuracy"] = 0.40
    d["metrics"]["ece"] = 0.20
    d["metrics"]["refusal_auroc"] = 0.55
    report = scan_benchmark_result(BenchmarkResult(**d))
    assert report.worst_severity == IssueSeverity.CRITICAL
    assert len(report.issues) >= 3
