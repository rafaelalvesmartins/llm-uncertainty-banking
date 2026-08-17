# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Unit tests for :mod:`lub.challenge.reports.cec_report` and the
OSCAL emit at :mod:`lub.challenge.reports.oscal_export`.

Spec: planning/24_CEC_Spec_2026-04-25.md §1.4 + §4 steps 4-6.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from lub.challenge import (
    AlternativeEstimator,
    AlternativeThreshold,
    CECReport,
    MetaCalibrator,
    assemble_cec_report,
    render_markdown,
)
from lub.challenge.reports.oscal_export import to_oscal_assessment_results
from tests.unit._cec_helpers import (
    attach_drift_events,
    deterministic_evidence_store,
    load_ledger_fixture,
)


def _period() -> tuple[datetime, datetime]:
    return datetime(2026, 4, 1), datetime(2026, 5, 1)


def test_assemble_cec_report_default_alternative() -> None:
    led = load_ledger_fixture()
    attach_drift_events(led)
    store = deterministic_evidence_store()
    start, end = _period()
    report = assemble_cec_report(start, end, ledger=led, evidence_store=store)
    assert isinstance(report, CECReport)
    assert report.period_start == start
    assert report.period_end == end
    assert len(report.replay_summary) == 1  # default AlternativeThreshold(0.85)
    assert len(report.drift_hypotheses) == 2
    assert report.meta_calibration_snapshot is not None
    assert isinstance(report.recommendations, list) and report.recommendations
    led.close()


def test_assemble_cec_report_with_multiple_alternatives() -> None:
    led = load_ledger_fixture()
    attach_drift_events(led)
    store = deterministic_evidence_store()
    start, end = _period()
    report = assemble_cec_report(
        start,
        end,
        ledger=led,
        evidence_store=store,
        replay_alternatives=[
            AlternativeThreshold(0.85),
            AlternativeEstimator("adaptive_conformal"),
        ],
    )
    assert len(report.replay_summary) == 2
    led.close()


def test_assemble_cec_report_validates_period() -> None:
    led = load_ledger_fixture()
    store = deterministic_evidence_store()
    with pytest.raises(ValueError, match="strictly after"):
        assemble_cec_report(
            datetime(2026, 5, 1),
            datetime(2026, 4, 1),
            ledger=led,
            evidence_store=store,
        )
    led.close()


def test_recommendations_flag_significant_drift() -> None:
    led = load_ledger_fixture()
    attach_drift_events(led)
    store = deterministic_evidence_store()
    start, end = _period()
    report = assemble_cec_report(start, end, ledger=led, evidence_store=store)
    rec_text = " ".join(report.recommendations)
    assert "significant" in rec_text or "calibration review" in rec_text
    led.close()


def test_recommendations_clean_period_returns_no_findings() -> None:
    """Empty window + no drift → no-findings boilerplate is emitted."""
    led = load_ledger_fixture()
    store = deterministic_evidence_store()
    report = assemble_cec_report(
        datetime(2025, 1, 1),
        datetime(2025, 1, 2),
        ledger=led,
        evidence_store=store,
    )
    rec_text = " ".join(report.recommendations).lower()
    assert "no material findings" in rec_text or "no recommendations" in rec_text
    led.close()


def test_signed_provenance_carries_repo_version() -> None:
    led = load_ledger_fixture()
    store = deterministic_evidence_store()
    start, end = _period()
    report = assemble_cec_report(start, end, ledger=led, evidence_store=store)
    assert "repo_version" in report.signed_provenance
    led.close()


def test_render_markdown_emits_all_sections() -> None:
    led = load_ledger_fixture()
    attach_drift_events(led)
    store = deterministic_evidence_store()
    start, end = _period()
    report = assemble_cec_report(start, end, ledger=led, evidence_store=store)
    md = render_markdown(report)
    for header in (
        "Continuous Effective Challenge",
        "Executive summary",
        "Replay findings",
        "Drift events explained",
        "Meta-calibration health",
        "Recommendations",
    ):
        assert header in md
    led.close()


def test_render_markdown_handles_no_drift_events() -> None:
    led = load_ledger_fixture()
    store = deterministic_evidence_store()
    start, end = _period()
    report = assemble_cec_report(start, end, ledger=led, evidence_store=store)
    md = render_markdown(report)
    assert "No drift events were detected in this period." in md
    led.close()


def test_oscal_export_top_level_envelope() -> None:
    led = load_ledger_fixture()
    attach_drift_events(led)
    store = deterministic_evidence_store()
    start, end = _period()
    report = assemble_cec_report(start, end, ledger=led, evidence_store=store)
    out = to_oscal_assessment_results(report)
    assert "assessment-results" in out
    ar = out["assessment-results"]
    assert "uuid" in ar and "metadata" in ar and "results" in ar
    assert ar["metadata"]["oscal-version"]
    assert len(ar["results"]) == 1
    led.close()


def test_oscal_export_observations_have_replay_and_drift() -> None:
    led = load_ledger_fixture()
    attach_drift_events(led)
    store = deterministic_evidence_store()
    start, end = _period()
    report = assemble_cec_report(start, end, ledger=led, evidence_store=store)
    out = to_oscal_assessment_results(report)
    obs = out["assessment-results"]["results"][0]["observations"]
    titles = [o["title"] for o in obs]
    assert any("Replay" in t for t in titles)
    assert any("Drift hypothesis" in t for t in titles)
    led.close()


def test_oscal_export_tags_airmf_controls() -> None:
    led = load_ledger_fixture()
    attach_drift_events(led)
    store = deterministic_evidence_store()
    start, end = _period()
    report = assemble_cec_report(start, end, ledger=led, evidence_store=store)
    out = to_oscal_assessment_results(report)
    block = out["assessment-results"]["results"][0]
    values = [p["value"] for p in block["props"]]
    assert "MANAGE 4.1" in values
    assert "MEASURE 2.7" in values
    led.close()


def test_oscal_export_is_json_serialisable() -> None:
    led = load_ledger_fixture()
    attach_drift_events(led)
    store = deterministic_evidence_store()
    start, end = _period()
    report = assemble_cec_report(start, end, ledger=led, evidence_store=store)
    out = to_oscal_assessment_results(report)
    # Will raise if any non-serialisable type slipped in.
    blob = json.dumps(out)
    assert "assessment-results" in blob
    led.close()


def test_oscal_export_rejects_none() -> None:
    with pytest.raises(ValueError):
        to_oscal_assessment_results(None)


def test_meta_calibration_snapshot_is_present_after_predictions() -> None:
    led = load_ledger_fixture()
    store = deterministic_evidence_store()
    mc = MetaCalibrator(ledger=led)
    for i in range(8):
        mc.add_prediction(f"c-{i}", 0.7, horizon_days=1)
        mc.record_outcome(f"c-{i}", held_up=(i % 2 == 0))
    start, end = _period()
    report = assemble_cec_report(start, end, ledger=led, evidence_store=store)
    snap = report.meta_calibration_snapshot
    assert snap is not None
    assert snap.ece >= 0.0
    led.close()
