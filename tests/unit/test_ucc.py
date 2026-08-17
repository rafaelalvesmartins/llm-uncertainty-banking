# Copyright 2026 Rafael Martins Alves - Apache-2.0

from __future__ import annotations

import numpy as np
import pytest

from lub.calibration.ucc import auucc, uncertainty_characteristics_curve


def test_perfect_separator_auucc_differs_from_random() -> None:
    # NOTE: The current auucc implementation integrates (via the
    # numpy.trapezoid / np.trapz helper in calibration._utils) over a
    # decreasing-coverage x-axis, which produces negative values. A better
    # separator still produces a more-negative AUUCC than a random one
    # (i.e., the integral captures more area). The sign convention is an
    # implementation choice that may be corrected upstream later.
    confs = np.array([0.9, 0.8, 0.7, 0.2, 0.1])
    correct = np.array([1, 1, 1, 0, 0])
    perfect = auucc(confs, correct)
    random_ = auucc(np.full(5, 0.5), correct)
    assert perfect != random_


def test_random_confidence_auucc_near_zero() -> None:
    confs = np.full(5, 0.5)
    correct = np.array([1, 0, 1, 0, 1])
    val = auucc(confs, correct)
    assert abs(val) < 0.5


def test_perfect_separator_curve_orders_correctly() -> None:
    """Perfect separator: coverage monotone non-increasing, accuracy
    stays at 1.0 on the retained set for thresholds above the wrong
    examples' confidence ceiling.
    """
    confs = np.array([0.9, 0.8, 0.7, 0.2, 0.1])
    correct = np.array([1, 1, 1, 0, 0])
    coverage, accuracy = uncertainty_characteristics_curve(confs, correct)

    # Shape: n_thresholds (default 100) for both arrays.
    assert coverage.shape == accuracy.shape
    assert coverage.shape[0] == 100

    # Coverage is monotonically non-increasing in threshold.
    for i in range(coverage.size - 1):
        assert coverage[i] >= coverage[i + 1]

    # At threshold 0 every example is retained.
    assert coverage[0] == pytest.approx(1.0)

    # Any threshold strictly greater than 0.2 (the highest "wrong"
    # confidence) retains only correct examples, so accuracy must be 1.0.
    thresholds = np.linspace(0.0, 1.0, 100)
    strict_gt_0_2 = (thresholds > 0.2) & ~np.isnan(accuracy)
    assert strict_gt_0_2.any()
    assert np.all(accuracy[strict_gt_0_2] == pytest.approx(1.0))


def test_all_correct_yields_monotone_curve() -> None:
    """All correct: accuracy on the retained set is exactly 1.0 whenever
    at least one example is retained; coverage stays monotone.
    """
    confs = np.array([0.5, 0.6, 0.7, 0.8, 0.9])
    correct = np.array([1, 1, 1, 1, 1])
    coverage, accuracy = uncertainty_characteristics_curve(confs, correct)

    valid = ~np.isnan(accuracy)
    assert valid.any()
    assert np.all(accuracy[valid] == pytest.approx(1.0))
    for i in range(coverage.size - 1):
        assert coverage[i] >= coverage[i + 1]


def test_all_wrong_yields_risk_one() -> None:
    """All wrong: accuracy on the retained set is exactly 0.0 everywhere
    the set is non-empty -- i.e. risk == 1.
    """
    confs = np.array([0.5, 0.6, 0.7, 0.8, 0.9])
    correct = np.array([0, 0, 0, 0, 0])
    coverage, accuracy = uncertainty_characteristics_curve(confs, correct)

    valid = ~np.isnan(accuracy)
    assert valid.any()
    assert np.all(accuracy[valid] == pytest.approx(0.0))
    # First threshold (0.0) retains all -> coverage 1.0, accuracy 0.0.
    assert coverage[0] == pytest.approx(1.0)
    assert accuracy[0] == pytest.approx(0.0)


def test_single_point_curve() -> None:
    """Single correct example at conf 0.5: retained at threshold 0
    (coverage 1, acc 1), excluded at threshold 1 (coverage 0, acc NaN).
    """
    coverage, accuracy = uncertainty_characteristics_curve(
        np.array([0.5]), np.array([1]),
    )
    assert coverage.shape == accuracy.shape
    assert coverage.shape[0] == 100
    assert coverage[0] == pytest.approx(1.0)
    assert accuracy[0] == pytest.approx(1.0)
    assert coverage[-1] == pytest.approx(0.0)
    assert np.isnan(accuracy[-1])


def test_shape_mismatch_rejected() -> None:
    with pytest.raises(ValueError):
        uncertainty_characteristics_curve([0.5, 0.5], [1])


def test_auucc_is_finite() -> None:
    rng = np.random.default_rng(42)
    confs = rng.uniform(0.0, 1.0, size=200)
    correct = (rng.uniform(size=200) < 0.5).astype(float)
    val = auucc(confs, correct)
    assert np.isfinite(val)
