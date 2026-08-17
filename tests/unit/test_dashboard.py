# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for lub.reports.dashboard.

Hermetic. Uses tmp_path fixtures with synthetic BenchmarkResult / OSCAL
JSONs. Covers:
  - empty / missing results_dir produces a warning-only dashboard
  - benchmark JSONs become per-estimator rows
  - OSCAL findings flow into the findings block
  - rendered HTML is well-formed and self-contained
  - ECE classification (ok / warn / fail thresholds)
  - build_dashboard writes file and creates parent dirs
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from lub.reports.dashboard import (
    DashboardCard,
    DashboardData,
    _classify_ece,
    _format_metric,
    build_dashboard,
    collect_dashboard_data,
    render_dashboard_html,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _benchmark_payload(
    estimator: str = "token_logprob",
    backend: str = "DummyBackend:dummy-0",
    dataset: str = "br_regulatory",
    n: int = 20,
    accuracy: float = 0.65,
    ece: float = 0.04,
    refusal_auroc: float = 0.81,
    prr: float = 0.55,
    brier: float = 0.18,
    rmsce: float = 0.05,
) -> dict:
    return {
        "repo_version": "v0.1.0",
        "backend": backend,
        "estimator": estimator,
        "dataset": dataset,
        "dataset_version": f"{dataset}:test",
        "n": n,
        "accuracy": accuracy,
        "ece": ece,
        "refusal_auroc": refusal_auroc,
        "prr": prr,
        "brier": brier,
        "rmsce": rmsce,
        "missing_ratio": 0.0,
        "dataset_hash": "deadbeef",
        "git_sha": "abc1234567",
        "python_version": "3.11.0",
        "package_versions": {},
        "seed": 0,
        "timestamp": "2026-04-25T10:00:00Z",
    }


def _oscal_payload(title: str = "AIRMF MEASURE 2.7 finding") -> dict:
    return {
        "assessment-results": {
            "uuid": "00000000-0000-0000-0000-000000000001",
            "metadata": {"title": "test", "oscal-version": "1.1.2"},
            "results": [
                {
                    "uuid": "00000000-0000-0000-0000-000000000002",
                    "title": "Test result",
                    "findings": [
                        {
                            "uuid": "00000000-0000-0000-0000-000000000003",
                            "title": title,
                            "description": "Test finding description.",
                            "target": {"target-id": "AIRMF-MEASURE-2.7"},
                            "related-observations": [
                                {"observation-uuid": "x"},
                                {"observation-uuid": "y"},
                            ],
                        }
                    ],
                }
            ],
        }
    }


_FIXED_NOW = _dt.datetime(2026, 4, 25, 18, 30, 0, tzinfo=_dt.UTC)


# ---------------------------------------------------------------------------
# Helpers under test
# ---------------------------------------------------------------------------


def test_format_metric_handles_none() -> None:
    assert _format_metric(None) == "-"


def test_format_metric_handles_nan() -> None:
    assert _format_metric(float("nan")) == "NaN"


def test_format_metric_default_places() -> None:
    assert _format_metric(0.123456) == "0.1235"


def test_format_metric_custom_places() -> None:
    assert _format_metric(0.123456, places=2) == "0.12"


def test_classify_ece_thresholds() -> None:
    assert _classify_ece(0.04) == "ok"
    assert _classify_ece(0.05) == "ok"
    assert _classify_ece(0.10) == "warn"
    assert _classify_ece(0.15) == "warn"
    assert _classify_ece(0.20) == "fail"
    assert _classify_ece(None) == "neutral"
    assert _classify_ece(float("nan")) == "neutral"


# ---------------------------------------------------------------------------
# collect_dashboard_data
# ---------------------------------------------------------------------------


def test_collect_missing_dir_emits_warning(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    data = collect_dashboard_data(missing, now=_FIXED_NOW)
    assert any("does not exist" in w for w in data.warnings)
    assert data.estimator_rows == []


def test_collect_empty_dir_emits_warning(tmp_path: Path) -> None:
    data = collect_dashboard_data(tmp_path, now=_FIXED_NOW)
    assert any("no benchmarkresult artefacts" in w.lower() for w in data.warnings)
    assert data.estimator_rows == []


def test_collect_picks_up_benchmark_json(tmp_path: Path) -> None:
    (tmp_path / "result_token_logprob.json").write_text(
        json.dumps(_benchmark_payload(estimator="token_logprob"))
    )
    data = collect_dashboard_data(tmp_path, now=_FIXED_NOW)
    assert len(data.estimator_rows) == 1
    row = data.estimator_rows[0]
    assert row["estimator"] == "token_logprob"
    assert row["dataset"] == "br_regulatory"
    assert row["ece"] == "0.0400"
    assert row["ece_class"] == "ok"


def test_collect_picks_up_oscal_findings(tmp_path: Path) -> None:
    (tmp_path / "oscal_assessment_results.json").write_text(
        json.dumps(_oscal_payload(title="Drift event Q2"))
    )
    data = collect_dashboard_data(tmp_path, now=_FIXED_NOW)
    assert any(f["title"] == "Drift event Q2" for f in data.cec_findings)


def test_collect_skips_unparseable_json(tmp_path: Path) -> None:
    (tmp_path / "broken.json").write_text("not valid json {")
    (tmp_path / "good.json").write_text(json.dumps(_benchmark_payload()))
    data = collect_dashboard_data(tmp_path, now=_FIXED_NOW)
    assert any("failed to parse" in w for w in data.warnings)
    assert len(data.estimator_rows) == 1


def test_collect_summary_cards_reflect_run_count(tmp_path: Path) -> None:
    for est in ("token_logprob", "perplexity", "p_true"):
        (tmp_path / f"r_{est}.json").write_text(
            json.dumps(_benchmark_payload(estimator=est))
        )
    data = collect_dashboard_data(tmp_path, now=_FIXED_NOW)
    runs = next(c for c in data.cards if c.label == "runs")
    assert runs.value == "3"


def test_collect_avg_ece_card_classifies_correctly(tmp_path: Path) -> None:
    (tmp_path / "good.json").write_text(json.dumps(_benchmark_payload(ece=0.03)))
    (tmp_path / "good2.json").write_text(json.dumps(_benchmark_payload(ece=0.05)))
    data = collect_dashboard_data(tmp_path, now=_FIXED_NOW)
    avg = next(c for c in data.cards if c.label == "avg ECE")
    assert avg.status == "ok"


def test_collect_avg_ece_warns_on_high_ece(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text(json.dumps(_benchmark_payload(ece=0.20)))
    data = collect_dashboard_data(tmp_path, now=_FIXED_NOW)
    avg = next(c for c in data.cards if c.label == "avg ECE")
    assert avg.status == "fail"


def test_collect_low_accuracy_warning_card(tmp_path: Path) -> None:
    """Acc=0 across all rows (the broken-benchmark scenario from the audit)."""
    (tmp_path / "broken1.json").write_text(json.dumps(_benchmark_payload(accuracy=0.0)))
    (tmp_path / "broken2.json").write_text(json.dumps(_benchmark_payload(accuracy=0.0)))
    data = collect_dashboard_data(tmp_path, now=_FIXED_NOW)
    avg_acc = next(c for c in data.cards if c.label == "avg accuracy")
    assert avg_acc.status == "warn"


# ---------------------------------------------------------------------------
# render_dashboard_html
# ---------------------------------------------------------------------------


def test_render_produces_well_formed_html() -> None:
    data = DashboardData(
        title="test",
        generated_at="2026-04-25T18:30:00+00:00",
        cards=[DashboardCard("runs", "5", "test", "ok")],
    )
    html = render_dashboard_html(data)
    assert html.startswith("<!doctype html>")
    assert "</html>" in html
    assert "test" in html


def test_render_escapes_html_in_title() -> None:
    data = DashboardData(
        title="<script>alert(1)</script>",
        generated_at="2026-04-25",
    )
    html = render_dashboard_html(data)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_no_external_resources() -> None:
    """Banks need offline-only. Ensure no http(s):// URLs in output (except harmless ones in CSS variables)."""
    data = DashboardData(title="t", generated_at="now")
    html = render_dashboard_html(data)
    # Allow zero http/https references -- the template uses only CSS, no CDN, no fonts, no images
    assert "http://" not in html
    assert "https://" not in html


def test_render_warnings_block_appears_when_warnings_present() -> None:
    data = DashboardData(
        title="t", generated_at="now", warnings=["something weird happened"]
    )
    html = render_dashboard_html(data)
    assert "something weird happened" in html
    assert "Warnings" in html


def test_render_empty_estimator_table_has_friendly_message() -> None:
    data = DashboardData(title="t", generated_at="now")
    html = render_dashboard_html(data)
    assert "No BenchmarkResult JSONs" in html


# ---------------------------------------------------------------------------
# build_dashboard end-to-end
# ---------------------------------------------------------------------------


def test_build_dashboard_writes_file(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    (results / "r.json").write_text(json.dumps(_benchmark_payload()))
    out = tmp_path / "dist" / "dashboard.html"

    written = build_dashboard(results, out, title="Q2 dashboard", now=_FIXED_NOW)

    assert written == out
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Q2 dashboard" in text
    assert "token_logprob" in text


def test_build_dashboard_creates_parent_dirs(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    out = tmp_path / "deep" / "nested" / "out" / "dash.html"
    build_dashboard(results, out, now=_FIXED_NOW)
    assert out.exists()


def test_build_dashboard_with_both_benchmark_and_oscal(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    (results / "result.json").write_text(json.dumps(_benchmark_payload()))
    (results / "oscal_ar.json").write_text(json.dumps(_oscal_payload()))
    out = tmp_path / "dash.html"
    build_dashboard(results, out, now=_FIXED_NOW)
    text = out.read_text(encoding="utf-8")
    assert "token_logprob" in text
    assert "AIRMF MEASURE 2.7" in text


def test_build_dashboard_offline_no_network_strings(tmp_path: Path) -> None:
    results = tmp_path / "r"
    results.mkdir()
    (results / "r.json").write_text(json.dumps(_benchmark_payload()))
    out = tmp_path / "dash.html"
    build_dashboard(results, out, now=_FIXED_NOW)
    text = out.read_text(encoding="utf-8")
    assert "http://" not in text
    assert "https://" not in text
    assert "<script src=" not in text  # no external scripts
    assert "<link rel" not in text  # no external stylesheets
