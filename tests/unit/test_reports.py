# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for the AI RMF report renderer."""

from __future__ import annotations

from pathlib import Path

import pytest

from lub.reports import AIRMFReporter, get_rmf_mapping
from lub.types import BenchmarkResult
from tests import make_benchmark_result


def _make_result(dataset: str = "br_regulatory") -> BenchmarkResult:
    return make_benchmark_result(
        dataset=dataset,
        git_sha="deadbeef",
        miscalibration_area=None,
        sharpness=None,
        missing_ratio=None,
        prr=None,
    )


def test_mapping_covers_core_metrics() -> None:
    rmf = get_rmf_mapping()
    for key in ("accuracy", "ece", "refusal_auroc"):
        assert key in rmf
        assert rmf[key]["subcategory"]
        assert rmf[key]["description"]


def test_render_markdown_contains_all_airmf_sections() -> None:
    reporter = AIRMFReporter(results=[_make_result()])
    md = reporter.render("md")
    assert "## Govern" in md
    assert "## Map" in md
    assert "## Measure" in md
    assert "## Manage" in md
    assert "DummyBackend" in md
    assert "token_logprob" in md
    assert "0.0800" in md  # ECE formatted


def test_render_shows_optional_reliability_fields_when_present() -> None:
    result = _make_result().model_copy(
        update={
            "miscalibration_area": 0.12,
            "sharpness": 0.34,
            "missing_ratio": 0.05,
            "prr": 0.72,
        }
    )
    md = AIRMFReporter(results=[result]).render("md")
    assert "Miscalibration Area" in md
    assert "0.1200" in md
    assert "Sharpness" in md
    assert "0.3400" in md
    assert "Missing Ratio" in md
    assert "0.0500" in md
    assert "PRR" in md
    assert "0.7200" in md


def test_render_hides_optional_fields_when_absent() -> None:
    md = AIRMFReporter(results=[_make_result()]).render("md")
    assert "Miscalibration Area" not in md
    assert "Sharpness" not in md
    assert "Missing Ratio" not in md
    # PRR metric row should be absent, but the word may appear in prose
    assert "| PRR |" not in md


def test_render_html_wraps_body() -> None:
    reporter = AIRMFReporter(results=[_make_result()], title="Unit Test Report")
    html = reporter.render("html")
    assert html.startswith("<!doctype html>")
    assert "Unit Test Report" in html
    assert "<table>" in html


def test_render_rejects_bad_format() -> None:
    reporter = AIRMFReporter(results=[_make_result()])
    with pytest.raises(ValueError):
        reporter.render("pdf")  # type: ignore[arg-type]


def test_empty_results_rejected() -> None:
    with pytest.raises(ValueError):
        AIRMFReporter(results=[])


def test_reliability_pngs_length_mismatch() -> None:
    with pytest.raises(ValueError):
        AIRMFReporter(results=[_make_result()], reliability_pngs=[None, None])


def test_save_writes_file(tmp_path: Path) -> None:
    reporter = AIRMFReporter(results=[_make_result()])
    out = reporter.save(tmp_path / "r.md", format="md")
    assert out.exists()
    assert "## Measure" in out.read_text(encoding="utf-8")
