# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the newly-added calibration metrics: NLL, pinball loss,
ENCE (expected normalized calibration error). RMSCE tests live in
``test_calibration_metrics.py``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from lub.calibration.metrics import (
    expected_calibration_error,
    expected_normalized_calibration_error,
)
from lub.calibration.scoring_rules import (
    negative_log_likelihood,
    pinball_loss,
)

# --- NLL ---------------------------------------------------------------


def test_nll_perfect_confident_forecast_is_near_zero() -> None:
    confs = np.array([1.0, 0.0, 1.0, 0.0])
    correct = np.array([1, 0, 1, 0])
    nll = negative_log_likelihood(confs, correct, eps=1e-9)
    # Clipping means log(1 - 1e-9) ~ -1e-9 per example.
    assert nll < 1e-7


def test_nll_confidently_wrong_is_large() -> None:
    confs = np.array([0.99, 0.99, 0.01, 0.01])
    correct = np.array([0, 0, 1, 1])  # confidently wrong on every example
    nll = negative_log_likelihood(confs, correct)
    # -log(0.01) ≈ 4.6; average of four such terms ≈ 4.6.
    assert nll > 4.0


def test_nll_0_5_is_log_2() -> None:
    confs = np.full(10, 0.5)
    correct = np.array([0, 1, 0, 1, 0, 1, 0, 1, 0, 1])
    assert negative_log_likelihood(confs, correct) == pytest.approx(math.log(2.0), abs=1e-9)


def test_nll_shape_mismatch_rejected() -> None:
    with pytest.raises(ValueError):
        negative_log_likelihood([0.5, 0.5], [1])


def test_nll_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        negative_log_likelihood([1.2, 0.5], [1, 0])


def test_nll_invalid_eps_rejected() -> None:
    with pytest.raises(ValueError):
        negative_log_likelihood([0.5], [1], eps=0.0)
    with pytest.raises(ValueError):
        negative_log_likelihood([0.5], [1], eps=0.9)


# --- Pinball loss ------------------------------------------------------


def test_pinball_perfect_quantile_is_zero() -> None:
    q = np.array([1.0, 2.0, 3.0])
    y = np.array([1.0, 2.0, 3.0])
    assert pinball_loss(q, y, tau=0.5) == 0.0
    assert pinball_loss(q, y, tau=0.1) == 0.0


def test_pinball_symmetric_at_median() -> None:
    # tau=0.5 pinball is half the mean absolute error.
    q = np.array([0.0, 0.0, 0.0])
    y = np.array([-1.0, 0.0, 1.0])
    # |−1| + |0| + |1| = 2; mean = 2/3; times 0.5 = 1/3.
    assert pinball_loss(q, y, tau=0.5) == pytest.approx(1.0 / 3.0)


def test_pinball_asymmetric_penalty() -> None:
    # tau=0.9 penalizes under-prediction (y > q) 9x more than over.
    q = np.array([0.0])
    assert pinball_loss(q, np.array([1.0]), tau=0.9) == pytest.approx(0.9)
    assert pinball_loss(q, np.array([-1.0]), tau=0.9) == pytest.approx(0.1)


def test_pinball_invalid_tau_rejected() -> None:
    with pytest.raises(ValueError):
        pinball_loss([0.0], [0.0], tau=0.0)
    with pytest.raises(ValueError):
        pinball_loss([0.0], [0.0], tau=1.0)


def test_pinball_shape_mismatch_rejected() -> None:
    with pytest.raises(ValueError):
        pinball_loss([0.0, 0.0], [0.0], tau=0.5)


# --- ENCE --------------------------------------------------------------


def test_ence_perfect_calibration_is_low() -> None:
    # With 2000 samples across 20 bins the per-bin sampling noise leaves
    # a residual ENCE around 0.10-0.15 even for a perfectly-calibrated
    # source; the threshold picks off gross miscalibration, not Monte
    # Carlo floor noise.
    rng = np.random.default_rng(0)
    confs = rng.uniform(0.1, 1.0, size=2000)
    correct = (rng.uniform(0.0, 1.0, size=2000) < confs).astype(float)
    assert expected_normalized_calibration_error(confs, correct, n_bins=20) < 0.2


def test_ence_amplifies_low_confidence_errors() -> None:
    # Two bins, each with the same absolute gap but different mean-conf.
    # ENCE should weight the low-conf gap more.
    confs = np.array([0.1] * 10 + [0.9] * 10)
    # Bin 1 (conf=0.1, n=10): set correct=2 → acc=0.2, gap=0.1, gap/conf=1.0
    correct = np.array([1, 1] + [0] * 8 + [1] * 10, dtype=float)
    # Bin 2 (conf=0.9, n=10): set correct=10 → acc=1.0, gap=0.1, gap/conf=0.111
    # ENCE will be (10/20)*1.0 + (10/20)*0.111 ≈ 0.556
    # ECE will be (10/20)*0.1 + (10/20)*0.1 = 0.1
    ece = expected_calibration_error(confs, correct, n_bins=15)
    ence = expected_normalized_calibration_error(confs, correct, n_bins=15)
    assert ence > ece
    assert ence == pytest.approx(0.556, abs=0.05)


def test_ence_ignores_zero_confidence_bin() -> None:
    # A bin at conf=0 would create division-by-zero; ENCE should return 0
    # for that bin's contribution.
    confs = np.array([0.0, 0.0, 0.5, 0.5])
    correct = np.array([0, 0, 1, 0])
    out = expected_normalized_calibration_error(confs, correct, n_bins=10)
    # Only the conf=0.5 bin contributes; acc=0.5, gap=0, so ENCE≈0.
    assert out == pytest.approx(0.0, abs=1e-9)


def test_ence_empty_rejected() -> None:
    with pytest.raises(ValueError):
        expected_normalized_calibration_error([], [])


def test_ence_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        expected_normalized_calibration_error([1.5, 0.5], [1, 0])
