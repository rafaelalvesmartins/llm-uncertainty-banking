# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Unit tests for :mod:`lub.challenge.meta_calibration`.

Spec: planning/24_CEC_Spec_2026-04-25.md §1.3 + §4 step 3.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lub.challenge import MetaCalibrator
from lub.challenge.meta_calibration import CalibrationCurve
from lub.ledger import Ledger
from lub.ledger.schema import SCHEMA_VERSION

# A claim only enters the reliability curve once its revisit horizon has
# elapsed. Tests below that assert curve arithmetic evaluate at a moment past
# the horizon they declare; the maturity gate itself is covered in
# tests/unit/test_meta_calibration_maturity.py.
_AFTER_HORIZON = datetime.now(UTC) + timedelta(days=2)


def test_schema_v2_migration_creates_cec_tables() -> None:
    led = Ledger(":memory:")
    tables = {
        r[0]
        for r in led._conn.execute(  # noqa: SLF001
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "cec_meta_predictions" in tables
    assert "cec_meta_outcomes" in tables
    led.close()


def test_schema_version_is_at_least_2() -> None:
    assert SCHEMA_VERSION >= 2


def test_add_prediction_and_record_outcome_round_trip() -> None:
    with Ledger(":memory:") as led:
        mc = MetaCalibrator(ledger=led)
        mc.add_prediction("c-1", 0.78, horizon_days=30)
        mc.record_outcome("c-1", held_up=True)
        rows = led._conn.execute(  # noqa: SLF001
            "SELECT predicted_confidence, horizon_days FROM cec_meta_predictions"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == pytest.approx(0.78)
        assert rows[0][1] == 30


def test_add_prediction_idempotent() -> None:
    with Ledger(":memory:") as led:
        mc = MetaCalibrator(ledger=led)
        mc.add_prediction("c-1", 0.5, horizon_days=10)
        mc.add_prediction("c-1", 0.9, horizon_days=20)  # ignored
        rows = led._conn.execute(  # noqa: SLF001
            "SELECT predicted_confidence FROM cec_meta_predictions"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == pytest.approx(0.5)


def test_record_outcome_for_unknown_claim_raises() -> None:
    with Ledger(":memory:") as led:
        mc = MetaCalibrator(ledger=led)
        with pytest.raises(KeyError, match="no prediction"):
            mc.record_outcome("ghost", held_up=True)


def test_add_prediction_validates_range() -> None:
    with Ledger(":memory:") as led:
        mc = MetaCalibrator(ledger=led)
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            mc.add_prediction("c", 1.5, horizon_days=30)
        with pytest.raises(ValueError, match="non-negative"):
            mc.add_prediction("c", 0.5, horizon_days=-1)


def test_constructor_validates_n_bins() -> None:
    with Ledger(":memory:") as led:
        with pytest.raises(ValueError):
            MetaCalibrator(ledger=led, n_bins=1)
        with pytest.raises(ValueError):
            MetaCalibrator(ledger=led, n_bins=200)


def test_reliability_curve_empty_returns_zero_ece() -> None:
    with Ledger(":memory:") as led:
        mc = MetaCalibrator(ledger=led, n_bins=10)
        curve = mc.reliability_curve()
        assert isinstance(curve, CalibrationCurve)
        assert len(curve.bins) == 10
        assert curve.ece == 0.0
        assert all(b[2] == 0 for b in curve.bins)


def test_reliability_curve_perfectly_calibrated_has_zero_ece() -> None:
    with Ledger(":memory:") as led:
        mc = MetaCalibrator(ledger=led, n_bins=10)
        # 10 claims at conf=0.5 — half hold_up=True yields hold_rate=0.5.
        for i in range(10):
            mc.add_prediction(f"c-{i}", 0.5, horizon_days=1)
            mc.record_outcome(f"c-{i}", held_up=(i < 5))
        curve = mc.reliability_curve(now=_AFTER_HORIZON)
        # Guard against passing vacuously: an empty curve also has ECE 0, so
        # assert the claims were actually counted before trusting the figure.
        assert sum(n for _, _, n in curve.bins) == 10
        assert curve.ece == pytest.approx(0.0, abs=1e-9)


def test_reliability_curve_overconfidence_increases_ece() -> None:
    with Ledger(":memory:") as led:
        mc = MetaCalibrator(ledger=led, n_bins=10)
        # All claims at conf=0.95; only 50% hold up → big gap.
        for i in range(10):
            mc.add_prediction(f"c-{i}", 0.95, horizon_days=1)
            mc.record_outcome(f"c-{i}", held_up=(i < 5))
        curve = mc.reliability_curve(now=_AFTER_HORIZON)
        assert curve.ece > 0.3


def test_reliability_curve_uses_configured_n_bins() -> None:
    with Ledger(":memory:") as led:
        mc = MetaCalibrator(ledger=led, n_bins=5)
        for i in range(5):
            mc.add_prediction(f"c-{i}", 0.5, horizon_days=1)
            mc.record_outcome(f"c-{i}", held_up=True)
        curve = mc.reliability_curve()
        assert len(curve.bins) == 5


def test_calibration_curve_dataclass_default_factories() -> None:
    cc = CalibrationCurve()
    assert cc.bins == []
    assert cc.ece == 0.0


def test_n_bins_default_is_ten() -> None:
    with Ledger(":memory:") as led:
        mc = MetaCalibrator(ledger=led)
        curve = mc.reliability_curve()
        assert len(curve.bins) == 10


def test_outcomes_only_count_for_paired_predictions() -> None:
    with Ledger(":memory:") as led:
        mc = MetaCalibrator(ledger=led)
        mc.add_prediction("a", 0.6, horizon_days=1)
        mc.add_prediction("b", 0.7, horizon_days=1)
        mc.record_outcome("a", held_up=True)
        # b has no outcome — excluded from curve.
        pairs = mc._paired_observations(now=_AFTER_HORIZON)  # noqa: SLF001
        assert len(pairs) == 1
        assert pairs[0][0] == pytest.approx(0.6)
