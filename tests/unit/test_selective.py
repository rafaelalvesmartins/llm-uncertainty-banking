# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import numpy as np
import pytest

from lub.calibration.selective import (
    area_under_risk_coverage,
    prediction_rejection_ratio,
    risk_coverage_curve,
)


def test_perfect_separator_has_prr_one() -> None:
    confs = np.array([0.9, 0.8, 0.7, 0.2, 0.1])
    correct = np.array([1, 1, 1, 0, 0])
    assert prediction_rejection_ratio(confs, correct) == pytest.approx(1.0, abs=1e-9)


def test_anticorrelated_ranking_has_low_prr() -> None:
    confs = np.array([0.1, 0.2, 0.3, 0.8, 0.9])
    correct = np.array([1, 1, 1, 0, 0])
    prr = prediction_rejection_ratio(confs, correct)
    assert prr == 0.0  # clipped to zero for worse-than-random rankings


def test_all_correct_edge_case_returns_zero() -> None:
    confs = np.array([0.5, 0.6, 0.7])
    correct = np.array([1, 1, 1])
    assert prediction_rejection_ratio(confs, correct) == 0.0


def test_risk_coverage_curve_shape_and_endpoints() -> None:
    confs = np.array([0.9, 0.5, 0.1])
    correct = np.array([1, 0, 1])
    coverage, risk = risk_coverage_curve(confs, correct)
    assert coverage.shape == (3,)
    assert risk.shape == (3,)
    assert coverage[0] == pytest.approx(1.0 / 3.0)
    assert coverage[-1] == pytest.approx(1.0)
    # At full coverage, risk equals overall error rate.
    assert risk[-1] == pytest.approx(1.0 / 3.0)


def test_risk_coverage_curve_is_monotone_in_coverage() -> None:
    rng = np.random.default_rng(42)
    confs = rng.uniform(0.0, 1.0, size=50)
    correct = (rng.uniform(0.0, 1.0, size=50) < confs).astype(float)
    coverage, _risk = risk_coverage_curve(confs, correct)
    assert np.all(np.diff(coverage) > 0)


def test_area_under_risk_coverage_in_unit_interval() -> None:
    rng = np.random.default_rng(0)
    confs = rng.uniform(0.0, 1.0, size=100)
    correct = rng.integers(0, 2, size=100).astype(float)
    auc = area_under_risk_coverage(confs, correct)
    assert 0.0 <= auc <= 1.0


def test_shape_mismatch_rejected() -> None:
    with pytest.raises(ValueError):
        risk_coverage_curve([0.5, 0.5], [1])


def test_out_of_range_confs_rejected() -> None:
    with pytest.raises(ValueError):
        prediction_rejection_ratio([1.5, 0.5], [1, 0])
