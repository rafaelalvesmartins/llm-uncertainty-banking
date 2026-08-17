# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for reports/giskard_reporter.py — batch reporter adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lub.reports.giskard_reporter import GiskardBatchReporter
from lub.types import BenchmarkResult
from tests import make_benchmark_result


@pytest.fixture
def healthy_result() -> BenchmarkResult:
    """A BenchmarkResult that should pass all vulnerability checks."""
    return make_benchmark_result()


@pytest.fixture
def unhealthy_result() -> BenchmarkResult:
    """A BenchmarkResult that triggers critical issues (low AUROC, low accuracy)."""
    r = make_benchmark_result(accuracy=0.40, refusal_auroc=0.55, ece=0.20)
    d = r.model_dump()
    d["metrics"]["accuracy"] = 0.40
    d["metrics"]["refusal_auroc"] = 0.55
    d["metrics"]["ece"] = 0.20
    return BenchmarkResult(**d)


def test_constructor_rejects_empty_list() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        GiskardBatchReporter([])


def test_constructor_accepts_single_result(healthy_result: BenchmarkResult) -> None:
    reporter = GiskardBatchReporter([healthy_result])
    assert reporter.results == [healthy_result]


def test_constructor_accepts_multiple_results(
    healthy_result: BenchmarkResult, unhealthy_result: BenchmarkResult
) -> None:
    reporter = GiskardBatchReporter([healthy_result, unhealthy_result])
    assert len(reporter.results) == 2


def test_render_json_returns_valid_json(healthy_result: BenchmarkResult) -> None:
    reporter = GiskardBatchReporter([healthy_result])
    out = reporter.render(format="json")
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    entry = parsed[0]
    assert entry["backend"] == healthy_result.backend
    assert entry["estimator"] == healthy_result.estimator
    assert entry["dataset"] == healthy_result.dataset
    assert "issues" in entry
    assert "passed" in entry


def test_render_json_default_format(healthy_result: BenchmarkResult) -> None:
    reporter = GiskardBatchReporter([healthy_result])
    out = reporter.render()
    parsed = json.loads(out)
    assert isinstance(parsed, list)


def test_render_json_multiple_results(
    healthy_result: BenchmarkResult, unhealthy_result: BenchmarkResult
) -> None:
    reporter = GiskardBatchReporter([healthy_result, unhealthy_result])
    parsed = json.loads(reporter.render(format="json"))
    assert len(parsed) == 2
    assert parsed[0]["passed"] is True
    assert parsed[1]["passed"] is False


def test_render_md_contains_header(healthy_result: BenchmarkResult) -> None:
    out = GiskardBatchReporter([healthy_result]).render(format="md")
    assert out.startswith("# Vulnerability Report (Giskard-style)")


def test_render_md_lists_each_run(
    healthy_result: BenchmarkResult, unhealthy_result: BenchmarkResult
) -> None:
    out = GiskardBatchReporter([healthy_result, unhealthy_result]).render(format="md")
    assert "## Run 1:" in out
    assert "## Run 2:" in out
    assert healthy_result.backend in out
    assert healthy_result.dataset in out


def test_render_md_clean_run_says_no_vulnerabilities() -> None:
    r = make_benchmark_result(ece=0.01, accuracy=0.90, refusal_auroc=0.90, missing_ratio=0.05)
    d = r.model_dump()
    d["metrics"].update(
        {"ece": 0.01, "accuracy": 0.90, "refusal_auroc": 0.90, "missing_ratio": 0.05}
    )
    clean = BenchmarkResult(**d)
    out = GiskardBatchReporter([clean]).render(format="md")
    assert "No vulnerabilities detected." in out
    assert "**Passed:** Yes" in out


def test_render_md_unhealthy_run_emits_table(unhealthy_result: BenchmarkResult) -> None:
    out = GiskardBatchReporter([unhealthy_result]).render(format="md")
    assert "| Severity | Category | Metric |" in out
    assert "**Passed:** No" in out
    assert "`accuracy`" in out or "`refusal_auroc`" in out


def test_render_md_reports_issue_count(unhealthy_result: BenchmarkResult) -> None:
    out = GiskardBatchReporter([unhealthy_result]).render(format="md")
    assert "**Issues found:**" in out
    assert "**Issues found:** 0" not in out


def test_render_md_includes_worst_severity_field(healthy_result: BenchmarkResult) -> None:
    out = GiskardBatchReporter([healthy_result]).render(format="md")
    assert "**Worst severity:**" in out


def test_save_writes_file_to_disk(
    tmp_path: Path, healthy_result: BenchmarkResult
) -> None:
    reporter = GiskardBatchReporter([healthy_result])
    out_path = tmp_path / "report.json"
    returned = reporter.save(out_path, format="json")
    assert returned == out_path
    assert out_path.exists()
    parsed = json.loads(out_path.read_text(encoding="utf-8"))
    assert isinstance(parsed, list)
    assert len(parsed) == 1


def test_save_creates_parent_dirs(
    tmp_path: Path, healthy_result: BenchmarkResult
) -> None:
    reporter = GiskardBatchReporter([healthy_result])
    out_path = tmp_path / "nested" / "subdir" / "report.md"
    reporter.save(out_path, format="md")
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert content.startswith("# Vulnerability Report")


def test_save_accepts_str_path(
    tmp_path: Path, healthy_result: BenchmarkResult
) -> None:
    reporter = GiskardBatchReporter([healthy_result])
    out_path = tmp_path / "report.json"
    returned = reporter.save(str(out_path), format="json")
    assert returned == out_path
    assert out_path.exists()


def test_json_output_preserves_issue_metric_values(
    unhealthy_result: BenchmarkResult,
) -> None:
    parsed = json.loads(GiskardBatchReporter([unhealthy_result]).render(format="json"))
    issues = parsed[0]["issues"]
    assert len(issues) > 0
    for issue in issues:
        assert "metric_name" in issue
        assert "metric_value" in issue
        assert "threshold" in issue
        assert "severity" in issue
        assert "category" in issue


def test_module_exports() -> None:
    from lub.reports import giskard_reporter

    assert "GiskardBatchReporter" in giskard_reporter.__all__
