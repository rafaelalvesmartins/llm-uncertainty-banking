# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for lub.challenge.meta_calibration."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import FrozenInstanceError

import pytest

from lub.challenge.meta_calibration import CalibrationCurve, MetaCalibrator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _StubLedger:
    """Minimal stand-in for lub.ledger.Ledger exposing ``_conn``."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn


@pytest.fixture()
def conn() -> Iterator[sqlite3.Connection]:
    """In-memory SQLite connection with the two CEC tables pre-created.

    ``created_at`` mirrors the real ledger schema (src/lub/ledger/schema.py),
    which ``_paired_observations`` reads to skip claims whose revisit horizon
    has not elapsed. The default is **backdated** here on purpose: the tests in
    this module exercise the reliability-curve arithmetic, so every claim they
    write should already be mature regardless of the horizon it declares. The
    maturity gate itself is covered separately in
    ``test_meta_calibration_maturity.py``.
    """
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE cec_meta_predictions (
            claim_id TEXT PRIMARY KEY,
            predicted_confidence REAL NOT NULL,
            horizon_days INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT '2000-01-01T00:00:00.000Z'
        );
        CREATE TABLE cec_meta_outcomes (
            claim_id TEXT PRIMARY KEY,
            held_up INTEGER NOT NULL
        );
        """
    )
    yield c
    c.close()


@pytest.fixture()
def ledger(conn: sqlite3.Connection) -> _StubLedger:
    return _StubLedger(conn)


@pytest.fixture()
def calibrator(ledger: _StubLedger) -> MetaCalibrator:
    return MetaCalibrator(ledger, n_bins=10)


# ---------------------------------------------------------------------------
# Construction / validation
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_bins(self, ledger: _StubLedger) -> None:
        c = MetaCalibrator(ledger)
        assert c._n_bins == 10

    def test_custom_bins(self, ledger: _StubLedger) -> None:
        c = MetaCalibrator(ledger, n_bins=20)
        assert c._n_bins == 20

    @pytest.mark.parametrize("n_bins", [0, 1, -5, 101, 200])
    def test_invalid_bins_raises(self, ledger: _StubLedger, n_bins: int) -> None:
        with pytest.raises(ValueError, match="n_bins must be in"):
            MetaCalibrator(ledger, n_bins=n_bins)

    def test_bins_boundary_values_accepted(self, ledger: _StubLedger) -> None:
        MetaCalibrator(ledger, n_bins=2)
        MetaCalibrator(ledger, n_bins=100)


# ---------------------------------------------------------------------------
# add_prediction
# ---------------------------------------------------------------------------


class TestAddPrediction:
    def test_inserts_row(
        self, calibrator: MetaCalibrator, conn: sqlite3.Connection
    ) -> None:
        calibrator.add_prediction("claim-1", 0.8, 30)
        row = conn.execute(
            "SELECT claim_id, predicted_confidence, horizon_days"
            " FROM cec_meta_predictions WHERE claim_id = 'claim-1'"
        ).fetchone()
        assert row["claim_id"] == "claim-1"
        assert row["predicted_confidence"] == pytest.approx(0.8)
        assert row["horizon_days"] == 30

    @pytest.mark.parametrize("conf", [0.0, 1.0, 0.5])
    def test_boundary_confidences_accepted(
        self, calibrator: MetaCalibrator, conf: float
    ) -> None:
        calibrator.add_prediction("c", conf, 0)

    @pytest.mark.parametrize("conf", [-0.01, 1.01, -1.0, 2.0])
    def test_invalid_confidence_raises(
        self, calibrator: MetaCalibrator, conf: float
    ) -> None:
        with pytest.raises(ValueError, match="predicted_confidence"):
            calibrator.add_prediction("c", conf, 30)

    def test_negative_horizon_raises(self, calibrator: MetaCalibrator) -> None:
        with pytest.raises(ValueError, match="horizon_days"):
            calibrator.add_prediction("c", 0.5, -1)

    def test_zero_horizon_accepted(self, calibrator: MetaCalibrator) -> None:
        calibrator.add_prediction("c", 0.5, 0)

    def test_duplicate_claim_id_is_ignored(
        self, calibrator: MetaCalibrator, conn: sqlite3.Connection
    ) -> None:
        calibrator.add_prediction("dup", 0.8, 30)
        calibrator.add_prediction("dup", 0.2, 60)
        rows = conn.execute(
            "SELECT predicted_confidence, horizon_days FROM cec_meta_predictions"
            " WHERE claim_id = 'dup'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["predicted_confidence"] == pytest.approx(0.8)
        assert rows[0]["horizon_days"] == 30

    def test_claim_id_is_coerced_to_string(
        self, calibrator: MetaCalibrator, conn: sqlite3.Connection
    ) -> None:
        calibrator.add_prediction(42, 0.5, 7)  # type: ignore[arg-type]
        row = conn.execute(
            "SELECT claim_id FROM cec_meta_predictions WHERE claim_id = '42'"
        ).fetchone()
        assert row is not None


# ---------------------------------------------------------------------------
# record_outcome
# ---------------------------------------------------------------------------


class TestRecordOutcome:
    def test_records_outcome(
        self, calibrator: MetaCalibrator, conn: sqlite3.Connection
    ) -> None:
        calibrator.add_prediction("c1", 0.7, 30)
        calibrator.record_outcome("c1", True)
        row = conn.execute(
            "SELECT held_up FROM cec_meta_outcomes WHERE claim_id = 'c1'"
        ).fetchone()
        assert row["held_up"] == 1

    def test_record_false_outcome(
        self, calibrator: MetaCalibrator, conn: sqlite3.Connection
    ) -> None:
        calibrator.add_prediction("c1", 0.7, 30)
        calibrator.record_outcome("c1", False)
        row = conn.execute(
            "SELECT held_up FROM cec_meta_outcomes WHERE claim_id = 'c1'"
        ).fetchone()
        assert row["held_up"] == 0

    def test_missing_prediction_raises_keyerror(
        self, calibrator: MetaCalibrator
    ) -> None:
        with pytest.raises(KeyError, match="no prediction recorded"):
            calibrator.record_outcome("nonexistent", True)

    def test_outcome_can_be_overwritten(
        self, calibrator: MetaCalibrator, conn: sqlite3.Connection
    ) -> None:
        calibrator.add_prediction("c1", 0.7, 30)
        calibrator.record_outcome("c1", True)
        calibrator.record_outcome("c1", False)
        rows = conn.execute(
            "SELECT held_up FROM cec_meta_outcomes WHERE claim_id = 'c1'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["held_up"] == 0


# ---------------------------------------------------------------------------
# reliability_curve
# ---------------------------------------------------------------------------


class TestReliabilityCurve:
    def test_empty_ledger_returns_zero_bins(
        self, calibrator: MetaCalibrator
    ) -> None:
        curve = calibrator.reliability_curve()
        assert isinstance(curve, CalibrationCurve)
        assert len(curve.bins) == 10
        # All bins empty, midpoints span [0.05, ..., 0.95]
        assert all(n == 0 for _, _, n in curve.bins)
        assert curve.ece == 0.0
        midpoints = [b[0] for b in curve.bins]
        assert midpoints[0] == pytest.approx(0.05)
        assert midpoints[-1] == pytest.approx(0.95)

    def test_predictions_without_outcomes_are_ignored(
        self, calibrator: MetaCalibrator
    ) -> None:
        calibrator.add_prediction("c1", 0.9, 30)
        calibrator.add_prediction("c2", 0.1, 30)
        curve = calibrator.reliability_curve()
        assert all(n == 0 for _, _, n in curve.bins)
        assert curve.ece == 0.0

    def test_perfectly_calibrated_yields_zero_ece(
        self, calibrator: MetaCalibrator
    ) -> None:
        # All predictions at 1.0 confidence, all held up.
        for i in range(10):
            calibrator.add_prediction(f"c{i}", 1.0, 30)
            calibrator.record_outcome(f"c{i}", True)
        curve = calibrator.reliability_curve()
        assert curve.ece == pytest.approx(0.0, abs=1e-9)

    def test_completely_wrong_predictions_yield_high_ece(
        self, calibrator: MetaCalibrator
    ) -> None:
        # Confidence 1.0 but never held up.
        for i in range(10):
            calibrator.add_prediction(f"c{i}", 1.0, 30)
            calibrator.record_outcome(f"c{i}", False)
        curve = calibrator.reliability_curve()
        assert curve.ece == pytest.approx(1.0, abs=1e-9)

    def test_ece_is_weighted_by_bin_size(
        self, calibrator: MetaCalibrator
    ) -> None:
        # Two bins, one large + perfect, one tiny + wrong.
        for i in range(9):
            calibrator.add_prediction(f"hi-{i}", 0.95, 30)
            calibrator.record_outcome(f"hi-{i}", True)
        calibrator.add_prediction("lo", 0.05, 30)
        calibrator.record_outcome("lo", True)  # bin error = |0.05 - 1| = 0.95
        curve = calibrator.reliability_curve()
        # 9 of 10 high-conf (error |0.95-1| = 0.05), 1 of 10 low-conf (error |0.05-1| = 0.95)
        # ECE = (9/10)*0.05 + (1/10)*0.95 = 0.045 + 0.095 = 0.14
        assert curve.ece == pytest.approx(0.14, abs=1e-3)

    def test_bin_counts_sum_to_paired_observations(
        self, calibrator: MetaCalibrator
    ) -> None:
        confs = [0.05, 0.25, 0.55, 0.75, 0.95]
        for i, c in enumerate(confs):
            calibrator.add_prediction(f"c{i}", c, 30)
            calibrator.record_outcome(f"c{i}", i % 2 == 0)
        curve = calibrator.reliability_curve()
        assert sum(n for _, _, n in curve.bins) == len(confs)

    def test_bin_count_matches_n_bins(self, ledger: _StubLedger) -> None:
        cal = MetaCalibrator(ledger, n_bins=5)
        curve = cal.reliability_curve()
        assert len(curve.bins) == 5

    def test_confidence_at_one_goes_into_last_bin(
        self, calibrator: MetaCalibrator
    ) -> None:
        # Edge case: conf == 1.0 should not overflow.
        calibrator.add_prediction("c", 1.0, 30)
        calibrator.record_outcome("c", True)
        curve = calibrator.reliability_curve()
        last = curve.bins[-1]
        assert last[2] == 1
        # All other bins empty
        assert all(b[2] == 0 for b in curve.bins[:-1])

    def test_confidence_at_zero_goes_into_first_bin(
        self, calibrator: MetaCalibrator
    ) -> None:
        calibrator.add_prediction("c", 0.0, 30)
        calibrator.record_outcome("c", False)
        curve = calibrator.reliability_curve()
        first = curve.bins[0]
        assert first[2] == 1
        assert all(b[2] == 0 for b in curve.bins[1:])

    def test_hold_rate_is_fraction_in_bin(
        self, calibrator: MetaCalibrator
    ) -> None:
        # Three predictions in same high-confidence bin: 2 held, 1 not.
        for i, held in enumerate([True, True, False]):
            calibrator.add_prediction(f"c{i}", 0.92, 30)
            calibrator.record_outcome(f"c{i}", held)
        curve = calibrator.reliability_curve()
        non_empty = [b for b in curve.bins if b[2] > 0]
        assert len(non_empty) == 1
        mean_conf, hold_rate, n = non_empty[0]
        assert n == 3
        assert mean_conf == pytest.approx(0.92)
        assert hold_rate == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# CalibrationCurve dataclass
# ---------------------------------------------------------------------------


class TestCalibrationCurve:
    def test_defaults(self) -> None:
        c = CalibrationCurve()
        assert c.bins == []
        assert c.ece == 0.0

    def test_is_frozen(self) -> None:
        c = CalibrationCurve()
        with pytest.raises(FrozenInstanceError):
            c.ece = 0.5  # type: ignore[misc]

    def test_construct_with_values(self) -> None:
        bins = [(0.5, 0.6, 4)]
        c = CalibrationCurve(bins=bins, ece=0.1)
        assert c.bins == bins
        assert c.ece == 0.1


# ---------------------------------------------------------------------------
# End-to-end pipeline scenario (ledger writes -> meta-curve)
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_full_cycle_predict_outcome_evaluate(
        self, calibrator: MetaCalibrator
    ) -> None:
        # Mimic CEC making claims, time passing, outcomes recorded.
        claims = [
            ("dom-shift", 0.78, True),
            ("dom-stable", 0.85, True),
            ("estimator-X", 0.40, False),
            ("estimator-Y", 0.60, True),
        ]
        for claim_id, conf, _ in claims:
            calibrator.add_prediction(claim_id, conf, horizon_days=30)
        for claim_id, _, held in claims:
            calibrator.record_outcome(claim_id, held)

        curve = calibrator.reliability_curve()
        assert sum(n for _, _, n in curve.bins) == len(claims)
        assert 0.0 <= curve.ece <= 1.0
