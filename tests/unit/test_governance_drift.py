# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :mod:`lub.governance.drift`.

This file is named ``test_governance_drift`` so it does not collide
with the pre-existing ``test_drift`` which covers ``calibration/drift.py``
(input drift + CBPE).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lub.governance.adr import PolicyViolation
from lub.governance.contexts import BoundedContext
from lub.governance.drift import (
    DriftReport,
    check_drift,
    compute_ece,
    enforce_drift,
)
from lub.ledger.store import CalibrationPoint, Ledger


def _ctx(target: float = 0.10) -> BoundedContext:
    return BoundedContext(
        name="regulatory-qa",
        domain="regulatory",
        calibration_target_ece=target,
        coverage_target=0.7,
        risk_ceiling=0.2,
        tier_order=["haiku", "sonnet"],
        abstain_marker="ABSTAIN",
    )


def _point(conf: float, acc: float, n: int, idx: int = 0) -> CalibrationPoint:
    return CalibrationPoint(
        bucket=idx,
        bucket_low=0.0,
        bucket_high=1.0,
        confidence_mean=conf,
        accuracy=acc,
        n=n,
    )


def test_compute_ece_perfectly_calibrated() -> None:
    pts = [_point(0.5, 0.5, 10, 0), _point(0.8, 0.8, 20, 1)]
    assert compute_ece(pts) == pytest.approx(0.0)


def test_compute_ece_weighted() -> None:
    # bucket A: |0.9 - 0.5| = 0.4 with n=10
    # bucket B: |0.6 - 0.7| = 0.1 with n=40
    # weighted = 0.2 * 0.4 + 0.8 * 0.1 = 0.16
    pts = [_point(0.9, 0.5, 10, 0), _point(0.6, 0.7, 40, 1)]
    assert compute_ece(pts) == pytest.approx(0.16)


def test_compute_ece_handles_empty_ledger() -> None:
    assert compute_ece([]) == 0.0


def _seed_ledger(path: Path, rows: list[tuple[float, int]]) -> None:
    """Seed a ledger with `rows = [(confidence, correct)]` tuples."""
    with Ledger(path) as led:
        for i, (conf, correct) in enumerate(rows):
            qid = led.log_query(prompt=f"q-{i}", domain="regulatory")
            aid = led.log_answer(
                query_id=qid,
                model="dummy",
                backend="dummy",
                answer=f"a-{i}",
                latency_ms=0,
                cost=0.0,
            )
            led.log_score(answer_id=aid, method="confidence", value=conf)
            led.update_outcome(
                answer_id=aid,
                ground_truth=f"a-{i}" if correct else "OTHER",
                human_verdict=None,
                correct=bool(correct),
            )


def test_check_drift_below_threshold(tmp_path: Path) -> None:
    path = tmp_path / "cal.sqlite"
    rows = [(0.9, 1)] * 18 + [(0.9, 0)] * 2
    _seed_ledger(path, rows)
    ctx = _ctx(target=0.20)
    with Ledger(path) as led:
        report = check_drift(led, ctx, n_buckets=5, min_samples=5)
    assert isinstance(report, DriftReport)
    assert report.passed is True
    assert report.n_samples == 20


def test_enforce_drift_raises_when_miscalibrated(tmp_path: Path) -> None:
    path = tmp_path / "cal.sqlite"
    rows = [(0.95, 1)] * 4 + [(0.95, 0)] * 16
    _seed_ledger(path, rows)
    ctx = _ctx(target=0.05)
    with Ledger(path) as led:
        with pytest.raises(PolicyViolation, match="calibration drift"):
            enforce_drift(led, ctx, n_buckets=5, min_samples=5)


def test_enforce_drift_inconclusive_when_ledger_cold(tmp_path: Path) -> None:
    path = tmp_path / "cal.sqlite"
    _seed_ledger(path, [(0.95, 0)] * 3)
    ctx = _ctx(target=0.01)
    with Ledger(path) as led:
        report = enforce_drift(led, ctx, n_buckets=5, min_samples=10)
    assert report.passed is True
    assert report.n_samples == 3


def test_drift_report_str_is_human_readable() -> None:
    report = DriftReport(
        context_name="retail-credit",
        method="confidence",
        measured_ece=0.12,
        target_ece=0.05,
        passed=False,
        n_samples=40,
    )
    s = str(report)
    assert "FAIL" in s
    assert "retail-credit" in s
    assert "0.1200" in s
