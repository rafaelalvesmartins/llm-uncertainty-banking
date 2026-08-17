# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the proper scoring rules in ``calibration/scoring_rules.py``.

Covers ``interval_score``, ``crps_gaussian``, and ``crps_from_confidence``
— the three functions in the module that did NOT have a dedicated test
file before. NLL and pinball loss live in
``tests/test_new_calibration_metrics.py``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from lub.calibration.scoring_rules import (
    crps_from_confidence,
    crps_gaussian,
    interval_score,
)

# --- interval_score ---------------------------------------------------


def test_interval_score_tight_covering_interval() -> None:
    # Perfectly-calibrated tight interval that covers the truth.
    lo = np.array([0.9, 1.9, 2.9])
    hi = np.array([1.1, 2.1, 3.1])
    actual = np.array([1.0, 2.0, 3.0])
    score = interval_score(lo, hi, actual, alpha=0.1)
    # Width only, no penalty. Mean width = 0.2.
    assert score == pytest.approx(0.2)


def test_interval_score_penalizes_miscoverage() -> None:
    lo = np.array([0.0, 0.0])
    hi = np.array([1.0, 1.0])
    actual = np.array([0.5, 5.0])  # second example outside interval
    score = interval_score(lo, hi, actual, alpha=0.1)
    # Example 1: width 1.0, no penalty.
    # Example 2: width 1.0, penalty 2/0.1 * (5 - 1) = 80.
    # Mean = (1 + 81) / 2 = 41.
    assert score == pytest.approx(41.0)


def test_interval_score_symmetric_under_lower_vs_upper_miscoverage() -> None:
    # Same-distance violations above and below score identically.
    actual = np.array([5.0])
    score_above = interval_score([0.0], [1.0], actual, alpha=0.2)
    score_below = interval_score([-1.0], [0.0], -actual, alpha=0.2)
    assert score_above == pytest.approx(score_below)


def test_interval_score_shape_mismatch_rejected() -> None:
    with pytest.raises(ValueError):
        interval_score([0.0, 0.0], [1.0], [0.5], alpha=0.1)


def test_interval_score_empty_rejected() -> None:
    with pytest.raises(ValueError):
        interval_score([], [], [], alpha=0.1)


def test_interval_score_invalid_alpha_rejected() -> None:
    with pytest.raises(ValueError):
        interval_score([0.0], [1.0], [0.5], alpha=0.0)
    with pytest.raises(ValueError):
        interval_score([0.0], [1.0], [0.5], alpha=1.0)


# --- crps_gaussian ----------------------------------------------------


def test_crps_gaussian_perfect_prediction_scales_with_std() -> None:
    # For a perfect-mean forecast (mean == actual, z=0), CRPS reduces to
    # sigma * (2*phi(0) - 1/sqrt(pi)) = sigma * (sqrt(2/pi) - 1/sqrt(pi)).
    mu = np.array([1.0])
    sigma = np.array([1.0])
    actual = np.array([1.0])
    score = crps_gaussian(mu, sigma, actual)
    expected = math.sqrt(2.0 / math.pi) - 1.0 / math.sqrt(math.pi)
    assert score == pytest.approx(expected, abs=1e-3)


def test_crps_gaussian_scales_linearly_with_sigma() -> None:
    # Double sigma → double CRPS at the perfect-mean point.
    mu = np.array([0.0])
    actual = np.array([0.0])
    one = crps_gaussian(mu, np.array([1.0]), actual)
    two = crps_gaussian(mu, np.array([2.0]), actual)
    assert two == pytest.approx(2.0 * one, rel=1e-3)


def test_crps_gaussian_miscoverage_increases_score() -> None:
    # Same sigma, but actual far from mean → higher CRPS.
    mu = np.array([0.0])
    sigma = np.array([1.0])
    near = crps_gaussian(mu, sigma, np.array([0.5]))
    far = crps_gaussian(mu, sigma, np.array([5.0]))
    assert far > near
    assert far > 2.0 * near


def test_crps_gaussian_averages_across_examples() -> None:
    # CRPS of three identical observations equals CRPS of one.
    mu = np.array([0.0, 0.0, 0.0])
    sigma = np.array([1.0, 1.0, 1.0])
    actual = np.array([0.5, 0.5, 0.5])
    batch = crps_gaussian(mu, sigma, actual)
    single = crps_gaussian(mu[:1], sigma[:1], actual[:1])
    assert batch == pytest.approx(single, rel=1e-6)


def test_crps_gaussian_rejects_nonpositive_std() -> None:
    with pytest.raises(ValueError):
        crps_gaussian([0.0], [0.0], [0.0])
    with pytest.raises(ValueError):
        crps_gaussian([0.0], [-1.0], [0.0])


def test_crps_gaussian_shape_mismatch_rejected() -> None:
    with pytest.raises(ValueError):
        crps_gaussian([0.0, 1.0], [1.0], [0.0])


def test_crps_gaussian_empty_rejected() -> None:
    with pytest.raises(ValueError):
        crps_gaussian([], [], [])


# --- crps_from_confidence --------------------------------------------


def test_crps_from_confidence_equals_brier() -> None:
    # Documented behavior: Bernoulli CRPS = Brier score.
    confs = np.array([0.9, 0.1, 0.5, 0.0])
    correct = np.array([1, 0, 1, 0])
    score = crps_from_confidence(confs, correct)
    # (0.1^2 + 0.1^2 + 0.5^2 + 0.0^2) / 4 = (0.01 + 0.01 + 0.25 + 0) / 4 = 0.0675
    assert score == pytest.approx(0.0675)


def test_crps_from_confidence_zero_on_perfect_prediction() -> None:
    assert crps_from_confidence([1.0, 0.0, 1.0], [1, 0, 1]) == pytest.approx(0.0)


def test_crps_from_confidence_shape_mismatch_rejected() -> None:
    with pytest.raises(ValueError):
        crps_from_confidence([0.5], [0, 1])


def test_crps_from_confidence_empty_rejected() -> None:
    with pytest.raises(ValueError):
        crps_from_confidence([], [])
