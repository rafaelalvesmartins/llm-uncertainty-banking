# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Unit tests for :mod:`lub.challenge.reports.cec_report`.

These tests complement the broader integration-style suite in
``test_challenge_reports.py`` by exercising the private helpers and
edge cases of the public API in isolation.
"""

from __future__ import annotations

from dataclasses import is_dataclass
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lub.challenge.drift_reasoning import DriftHypothesis
from lub.challenge.meta_calibration import CalibrationCurve
from lub.challenge.replay import (
    AlternativeThreshold,
    ReplayReport,
)
from lub.challenge.reports import cec_report as cec_mod
from lub.challenge.reports.cec_report import (
    CECReport,
    _capture_provenance,
    _generate_recommendations,
    _hash_pkg_map,
    _list_drift_events_in_window,
    assemble_cec_report,
    render_markdown,
)
from tests.unit._cec_helpers import (
    attach_drift_events,
    deterministic_evidence_store,
    load_ledger_fixture,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def period() -> tuple[datetime, datetime]:
    return datetime(2026, 4, 1), datetime(2026, 5, 1)


@pytest.fixture()
def seeded_ledger():
    led = load_ledger_fixture()
    attach_drift_events(led)
    try:
        yield led
    finally:
        led.close()


@pytest.fixture()
def empty_ledger():
    led = load_ledger_fixture()
    try:
        yield led
    finally:
        led.close()


@pytest.fixture()
def evidence_store():
    return deterministic_evidence_store()


# ---------------------------------------------------------------------------
# CECReport dataclass
# ---------------------------------------------------------------------------


def test_cec_report_is_frozen_dataclass(period: tuple[datetime, datetime]) -> None:
    start, end = period
    report = CECReport(period_start=start, period_end=end)
    assert is_dataclass(report)
    assert report.replay_summary == []
    assert report.drift_hypotheses == []
    assert report.meta_calibration_snapshot is None
    assert report.recommendations == []
    assert report.signed_provenance == {}
    # Frozen — should reject in-place mutation.
    with pytest.raises(Exception):
        report.period_start = datetime(2026, 1, 1)  # type: ignore[misc]


def test_cec_report_default_collections_are_independent() -> None:
    a = CECReport(period_start=datetime(2026, 1, 1), period_end=datetime(2026, 2, 1))
    b = CECReport(period_start=datetime(2026, 2, 1), period_end=datetime(2026, 3, 1))
    a.recommendations.append("test")
    assert b.recommendations == []


# ---------------------------------------------------------------------------
# _list_drift_events_in_window
# ---------------------------------------------------------------------------


def test_list_drift_events_filters_by_window() -> None:
    ledger = SimpleNamespace(
        drift_events={
            "in": {"detected_at": "2026-04-15T12:00:00"},
            "before": {"detected_at": "2026-03-15T12:00:00"},
            "after": {"detected_at": "2026-06-15T12:00:00"},
        }
    )
    store = SimpleNamespace()
    out = _list_drift_events_in_window(
        datetime(2026, 4, 1), datetime(2026, 5, 1), ledger, store
    )
    assert out == ["in"]


def test_list_drift_events_dedup_across_sources() -> None:
    payload = {"x": {"detected_at": "2026-04-15T12:00:00"}}
    ledger = SimpleNamespace(drift_events=payload)
    store = SimpleNamespace(drift_events=payload)
    out = _list_drift_events_in_window(
        datetime(2026, 4, 1), datetime(2026, 5, 1), ledger, store
    )
    assert out == ["x"]


def test_list_drift_events_includes_unparseable_or_missing_ts() -> None:
    ledger = SimpleNamespace(
        drift_events={
            "no-ts": {},
            "bad-ts": {"detected_at": "not-a-date"},
            "z-suffix": {"detected_at": "2026-04-10T00:00:00Z"},
        }
    )
    store = SimpleNamespace()
    out = _list_drift_events_in_window(
        datetime(2026, 4, 1), datetime(2026, 5, 1), ledger, store
    )
    assert set(out) == {"no-ts", "bad-ts", "z-suffix"}


def test_list_drift_events_handles_missing_attribute() -> None:
    ledger = SimpleNamespace()
    store = SimpleNamespace()
    out = _list_drift_events_in_window(
        datetime(2026, 4, 1), datetime(2026, 5, 1), ledger, store
    )
    assert out == []


# ---------------------------------------------------------------------------
# _generate_recommendations
# ---------------------------------------------------------------------------


def _replay_report(baseline: float, counterfactual: float) -> ReplayReport:
    return ReplayReport(
        window_start=datetime(2026, 4, 1),
        window_end=datetime(2026, 5, 1),
        alternative=AlternativeThreshold(0.85),
        sample_size=10,
        baseline_abstention_rate=baseline,
        counterfactual_abstention_rate=counterfactual,
        baseline_correctness_rate=0.9,
        counterfactual_correctness_rate=0.9,
        cost_delta_estimate=0.0,
        audit_trail={},
    )


def test_generate_recommendations_flags_replay_delta_above_threshold() -> None:
    rr = _replay_report(0.10, 0.20)  # +10 pp swing
    recs = _generate_recommendations([rr], [], None)
    assert any("raises" in r and "10.0" in r for r in recs)


def test_generate_recommendations_ignores_small_replay_delta() -> None:
    rr = _replay_report(0.10, 0.11)  # +1 pp swing, below 5 pp gate
    recs = _generate_recommendations([rr], [], None)
    assert not any("Replay finding" in r for r in recs)


def test_generate_recommendations_flags_significant_drift() -> None:
    dh = DriftHypothesis(
        drift_event_id="drift-1",
        hypothesis="distribution-shift",
        support_evidence_ids=[],
        similarity_score=0.8,
        metadata={"severity": "significant"},
    )
    recs = _generate_recommendations([], [dh], None)
    assert any("significant PSI" in r and "drift-1" in r for r in recs)


def test_generate_recommendations_flags_moderate_drift() -> None:
    dh = DriftHypothesis(
        drift_event_id="drift-2",
        hypothesis="distribution-shift",
        support_evidence_ids=[],
        similarity_score=0.5,
        metadata={"severity": "moderate"},
    )
    recs = _generate_recommendations([], [dh], None)
    assert any("moderate PSI" in r and "drift-2" in r for r in recs)


def test_generate_recommendations_flags_high_meta_ece() -> None:
    curve = CalibrationCurve(bins=[], ece=0.25)
    recs = _generate_recommendations([], [], curve)
    assert any("Meta-calibration" in r and "0.25" in r for r in recs)


def test_generate_recommendations_low_ece_silent() -> None:
    curve = CalibrationCurve(bins=[], ece=0.05)
    recs = _generate_recommendations([], [], curve)
    assert not any("Meta-calibration" in r for r in recs)


def test_generate_recommendations_no_findings_boilerplate() -> None:
    recs = _generate_recommendations([], [], None)
    assert len(recs) == 1
    assert "No material findings" in recs[0]


# ---------------------------------------------------------------------------
# _capture_provenance / _hash_pkg_map
# ---------------------------------------------------------------------------


def test_hash_pkg_map_is_deterministic_and_order_invariant() -> None:
    a = _hash_pkg_map({"x": "1", "y": "2"})
    b = _hash_pkg_map({"y": "2", "x": "1"})
    assert a == b
    assert len(a) == 16


def test_hash_pkg_map_distinguishes_different_inputs() -> None:
    assert _hash_pkg_map({"x": "1"}) != _hash_pkg_map({"x": "2"})


def test_capture_provenance_returns_expected_keys() -> None:
    prov = _capture_provenance()
    assert "repo_version" in prov
    assert "git_sha" in prov


def test_capture_provenance_swallows_exceptions() -> None:
    with patch(
        "lub.benchmarks.provenance.Provenance.capture",
        side_effect=RuntimeError("boom"),
    ):
        prov = _capture_provenance()
    assert prov["repo_version"] == "unknown"
    assert prov["git_sha"] is None


# ---------------------------------------------------------------------------
# assemble_cec_report
# ---------------------------------------------------------------------------


def test_assemble_cec_report_returns_cec_report_instance(
    seeded_ledger, evidence_store, period: tuple[datetime, datetime]
) -> None:
    start, end = period
    report = assemble_cec_report(start, end, seeded_ledger, evidence_store)
    assert isinstance(report, CECReport)
    assert report.period_start == start
    assert report.period_end == end


def test_assemble_cec_report_default_alternative_yields_single_replay(
    seeded_ledger, evidence_store, period: tuple[datetime, datetime]
) -> None:
    start, end = period
    report = assemble_cec_report(start, end, seeded_ledger, evidence_store)
    assert len(report.replay_summary) == 1


def test_assemble_cec_report_rejects_inverted_period(
    empty_ledger, evidence_store
) -> None:
    with pytest.raises(ValueError, match="strictly after"):
        assemble_cec_report(
            datetime(2026, 5, 1),
            datetime(2026, 4, 1),
            empty_ledger,
            evidence_store,
        )


def test_assemble_cec_report_rejects_zero_length_period(
    empty_ledger, evidence_store
) -> None:
    same = datetime(2026, 4, 1)
    with pytest.raises(ValueError, match="strictly after"):
        assemble_cec_report(same, same, empty_ledger, evidence_store)


def test_assemble_cec_report_includes_drift_hypotheses_in_window(
    seeded_ledger, evidence_store, period: tuple[datetime, datetime]
) -> None:
    start, end = period
    report = assemble_cec_report(start, end, seeded_ledger, evidence_store)
    assert len(report.drift_hypotheses) == 2


def test_assemble_cec_report_skips_drift_outside_window(
    empty_ledger, evidence_store
) -> None:
    attach_drift_events(empty_ledger)
    report = assemble_cec_report(
        datetime(2025, 1, 1),
        datetime(2025, 1, 2),
        empty_ledger,
        evidence_store,
    )
    assert report.drift_hypotheses == []


def test_assemble_cec_report_swallows_meta_calibration_errors(
    seeded_ledger, evidence_store, period: tuple[datetime, datetime]
) -> None:
    start, end = period
    with patch.object(
        cec_mod, "MetaCalibrator", side_effect=RuntimeError("no curve")
    ):
        report = assemble_cec_report(start, end, seeded_ledger, evidence_store)
    assert report.meta_calibration_snapshot is None


def test_assemble_cec_report_populates_provenance(
    seeded_ledger, evidence_store, period: tuple[datetime, datetime]
) -> None:
    start, end = period
    report = assemble_cec_report(start, end, seeded_ledger, evidence_store)
    assert "repo_version" in report.signed_provenance


def test_assemble_cec_report_honours_custom_alternatives(
    seeded_ledger, evidence_store, period: tuple[datetime, datetime]
) -> None:
    start, end = period
    alts = [AlternativeThreshold(0.70), AlternativeThreshold(0.95)]
    report = assemble_cec_report(
        start, end, seeded_ledger, evidence_store, replay_alternatives=alts
    )
    assert len(report.replay_summary) == 2


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------


def test_render_markdown_returns_non_empty_string(
    seeded_ledger, evidence_store, period: tuple[datetime, datetime]
) -> None:
    start, end = period
    report = assemble_cec_report(start, end, seeded_ledger, evidence_store)
    md = render_markdown(report)
    assert isinstance(md, str)
    assert md.strip()


def test_render_markdown_contains_core_section_headers(
    seeded_ledger, evidence_store, period: tuple[datetime, datetime]
) -> None:
    start, end = period
    report = assemble_cec_report(start, end, seeded_ledger, evidence_store)
    md = render_markdown(report)
    for header in ("Continuous Effective Challenge", "Recommendations"):
        assert header in md
