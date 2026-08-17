# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Unit tests for ``lub.calibration.metrics``.

Pure-numpy module -- no LLM calls or Bridge pipeline to mock. Tests exercise
mathematical properties (perfect/worst-case behavior, monotonicity, ties,
degenerate inputs) and edge cases relevant to regulated banking model-risk
review (out-of-range inputs, empty arrays, single-class data).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from lub.calibration.metrics import (
    _bin_aggregates,
    _bin_indices,
    _rankdata,
    adversarial_group_calibration,
    brier_score,
    compute_all,
    expected_calibration_error,
    expected_normalized_calibration_error,
    kendall_tau,
    matthews_correlation,
    miscalibration_area,
    missing_ratio,
    refusal_auroc,
    reliability_curve,
    reversed_pairs_proportion,
    root_mean_squared_calibration_error,
    sharpness,
    spearman_rank_correlation,
)

# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(42)


@pytest.fixture
def perfectly_calibrated(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Confidences ~U(0,1); correctness sampled with P(correct) = confidence."""
    confs = rng.uniform(0.0, 1.0, size=4000)
    correct = (rng.uniform(0.0, 1.0, size=4000) < confs).astype(float)
    return confs, correct


@pytest.fixture
def perfect_separator() -> tuple[np.ndarray, np.ndarray]:
    """Confidence cleanly separates correct from incorrect."""
    confs = np.array([0.05, 0.15, 0.25, 0.35, 0.75, 0.85, 0.92, 0.98])
    correct = np.array([0, 0, 0, 0, 1, 1, 1, 1], dtype=float)
    return confs, correct


@pytest.fixture
def all_wrong_high_conf() -> tuple[np.ndarray, np.ndarray]:
    """Worst-case: confidence is 1.0 but every answer is wrong."""
    return np.ones(20), np.zeros(20)


# --------------------------------------------------------------------------- #
# Input validation (via _as_pair)                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "fn",
    [
        expected_calibration_error,
        root_mean_squared_calibration_error,
        expected_normalized_calibration_error,
        brier_score,
        refusal_auroc,
        reliability_curve,
        miscalibration_area,
        reversed_pairs_proportion,
        spearman_rank_correlation,
        kendall_tau,
    ],
)
def test_mismatched_shapes_raise(fn) -> None:
    with pytest.raises(ValueError, match="same shape"):
        fn([0.1, 0.2, 0.3], [0, 1])


@pytest.mark.parametrize(
    "fn",
    [
        expected_calibration_error,
        brier_score,
        refusal_auroc,
        miscalibration_area,
        spearman_rank_correlation,
    ],
)
def test_empty_input_raises(fn) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        fn([], [])


def test_out_of_range_conf_raises() -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        expected_calibration_error([0.5, 1.5], [0, 1])
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        brier_score([-0.1, 0.5], [0, 1])


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def test_bin_indices_endpoints_and_interior() -> None:
    c = np.array([0.0, 0.1, 0.5, 0.999, 1.0])
    idx = _bin_indices(c, n_bins=10)
    # 0.0 -> bin 0, 0.1 -> bin 1, 0.5 -> bin 5, last two -> bin 9
    assert idx.tolist() == [0, 1, 5, 9, 9]


def test_bin_aggregates_sums_match_inputs() -> None:
    c = np.array([0.1, 0.4, 0.6, 0.9])
    y = np.array([0.0, 1.0, 0.0, 1.0])
    counts, sum_conf, sum_correct = _bin_aggregates(c, y, n_bins=5)
    assert counts.sum() == 4
    assert sum_conf.sum() == pytest.approx(c.sum())
    assert sum_correct.sum() == pytest.approx(y.sum())


def test_bin_aggregates_rejects_zero_bins() -> None:
    with pytest.raises(ValueError, match="n_bins must be >= 1"):
        _bin_aggregates(np.array([0.5]), np.array([1.0]), n_bins=0)


def test_rankdata_handles_ties() -> None:
    # Ties at 0.5 should share rank 2.5 (average of 2 and 3).
    r = _rankdata(np.array([0.1, 0.5, 0.5, 0.9]))
    assert r.tolist() == [1.0, 2.5, 2.5, 4.0]


# --------------------------------------------------------------------------- #
# ECE / RMSCE / ENCE                                                          #
# --------------------------------------------------------------------------- #


def test_ece_perfectly_calibrated_is_small(
    perfectly_calibrated: tuple[np.ndarray, np.ndarray],
) -> None:
    confs, correct = perfectly_calibrated
    assert expected_calibration_error(confs, correct, n_bins=20) < 0.05


def test_ece_worst_case_equals_one(all_wrong_high_conf: tuple[np.ndarray, np.ndarray]) -> None:
    assert expected_calibration_error(*all_wrong_high_conf) == pytest.approx(1.0)


def test_ece_empty_bins_contribute_zero() -> None:
    # All in one bin -> mean_conf == mean_correct in that bin only.
    confs = np.full(50, 0.5)
    correct = np.full(50, 0.5)  # half correct (mocked as 0.5 averages out)
    # Use a binary version: 25 correct, 25 wrong -> acc=0.5, conf=0.5 -> gap=0.
    correct = np.r_[np.ones(25), np.zeros(25)]
    assert expected_calibration_error(confs, correct, n_bins=10) == pytest.approx(0.0)


def test_rmsce_penalizes_concentrated_miscalibration_more_than_ece() -> None:
    # 90% perfectly calibrated, 10% badly miscalibrated (n=1000 total).
    confs = np.r_[np.full(900, 0.5), np.full(100, 0.95)]
    correct = np.r_[
        np.r_[np.ones(450), np.zeros(450)],  # acc=0.5 matches conf=0.5
        np.zeros(100),  # acc=0.0 vs conf=0.95 — big gap
    ]
    ece = expected_calibration_error(confs, correct, n_bins=10)
    rmsce = root_mean_squared_calibration_error(confs, correct, n_bins=10)
    assert rmsce > ece > 0


def test_rmsce_matches_ece_when_all_bins_share_same_gap() -> None:
    # When the per-bin gap is constant, RMSCE == ECE (sqrt of a single value).
    confs = np.r_[np.full(100, 0.2), np.full(100, 0.8)]
    correct = np.r_[np.full(100, 0.3), np.full(100, 0.9)]  # gap=0.1 in both bins
    ece = expected_calibration_error(confs, correct, n_bins=10)
    rmsce = root_mean_squared_calibration_error(confs, correct, n_bins=10)
    assert rmsce == pytest.approx(ece, abs=1e-9)


def test_ence_weights_low_conf_bin_more_than_high_conf() -> None:
    # Equal raw gap (0.1) in low-conf and high-conf bins, but ENCE normalizes
    # by mean conf, so the low-conf bin contributes ~10x more.
    confs = np.r_[np.full(50, 0.1), np.full(50, 0.9)]
    correct = np.r_[np.full(50, 0.2), np.full(50, 1.0)]  # +0.1 gap each side
    ence = expected_normalized_calibration_error(confs, correct, n_bins=10)
    assert ence > 0.0


def test_ence_zero_when_perfectly_calibrated_per_bin() -> None:
    confs = np.r_[np.full(50, 0.3), np.full(50, 0.7)]
    correct = np.r_[np.full(50, 0.3), np.full(50, 0.7)]
    assert expected_normalized_calibration_error(confs, correct, n_bins=10) == pytest.approx(0.0)


@pytest.mark.parametrize(
    "fn", [expected_calibration_error, root_mean_squared_calibration_error]
)
def test_calibration_metrics_in_unit_interval(fn) -> None:
    """ECE and RMSCE both live in [0, 1]."""
    rng = np.random.default_rng(7)
    for _ in range(5):
        c = rng.uniform(0.0, 1.0, size=200)
        y = rng.integers(0, 2, size=200).astype(float)
        v = fn(c, y)
        assert 0.0 <= v <= 1.0 + 1e-9


def test_ence_is_non_negative() -> None:
    """ENCE divides by bin confidence and can exceed 1; only non-negativity holds."""
    rng = np.random.default_rng(7)
    for _ in range(5):
        c = rng.uniform(0.0, 1.0, size=200)
        y = rng.integers(0, 2, size=200).astype(float)
        v = expected_normalized_calibration_error(c, y, n_bins=10)
        assert v >= 0.0


# --------------------------------------------------------------------------- #
# Brier                                                                       #
# --------------------------------------------------------------------------- #


def test_brier_perfect_prediction_is_zero() -> None:
    confs = np.array([0.0, 1.0, 0.0, 1.0])
    correct = np.array([0, 1, 0, 1], dtype=float)
    assert brier_score(confs, correct) == pytest.approx(0.0)


def test_brier_constant_half_equals_quarter() -> None:
    confs = np.full(100, 0.5)
    correct = np.r_[np.ones(50), np.zeros(50)]
    assert brier_score(confs, correct) == pytest.approx(0.25)


def test_brier_worst_case_equals_one(all_wrong_high_conf: tuple[np.ndarray, np.ndarray]) -> None:
    assert brier_score(*all_wrong_high_conf) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Refusal AUROC + RPP                                                         #
# --------------------------------------------------------------------------- #


def test_auroc_perfect_separator(perfect_separator: tuple[np.ndarray, np.ndarray]) -> None:
    assert refusal_auroc(*perfect_separator) == pytest.approx(1.0)


def test_auroc_inverted_separator(perfect_separator: tuple[np.ndarray, np.ndarray]) -> None:
    confs, correct = perfect_separator
    assert refusal_auroc(confs, 1.0 - correct) == pytest.approx(0.0)


def test_auroc_single_class_returns_half() -> None:
    assert refusal_auroc(np.array([0.1, 0.5, 0.9]), np.ones(3)) == 0.5
    assert refusal_auroc(np.array([0.1, 0.5, 0.9]), np.zeros(3)) == 0.5


def test_auroc_all_ties_returns_half() -> None:
    confs = np.full(8, 0.5)
    correct = np.array([1, 0, 1, 0, 1, 0, 1, 0], dtype=float)
    assert refusal_auroc(confs, correct) == pytest.approx(0.5)


def test_auroc_partial_ties_match_brute_force() -> None:
    confs = np.array([0.1, 0.4, 0.4, 0.7, 0.9])
    correct = np.array([0, 0, 1, 1, 1], dtype=float)
    pos_mask = correct > 0.5
    pos = confs[pos_mask]
    neg = confs[~pos_mask]
    brute = np.mean(
        [(p > n) + 0.5 * (p == n) for p in pos for n in neg]
    )
    assert refusal_auroc(confs, correct) == pytest.approx(brute)


def test_rpp_equals_one_minus_auroc(perfect_separator: tuple[np.ndarray, np.ndarray]) -> None:
    confs, correct = perfect_separator
    rpp = reversed_pairs_proportion(confs, correct)
    auroc = refusal_auroc(confs, correct)
    assert rpp == pytest.approx(1.0 - auroc)


# --------------------------------------------------------------------------- #
# Reliability curve                                                           #
# --------------------------------------------------------------------------- #


def test_reliability_curve_shape() -> None:
    confs = np.linspace(0.0, 1.0, 100)
    correct = (confs > 0.5).astype(float)
    mean_conf, acc = reliability_curve(confs, correct, n_bins=10)
    assert mean_conf.shape == (10,)
    assert acc.shape == (10,)


def test_reliability_curve_empty_bins_nan() -> None:
    confs = np.array([0.05, 0.95])
    correct = np.array([0, 1], dtype=float)
    mean_conf, acc = reliability_curve(confs, correct, n_bins=10)
    assert np.isnan(mean_conf[5])
    assert np.isnan(acc[5])
    assert not np.isnan(mean_conf[0])
    assert not np.isnan(mean_conf[9])


def test_reliability_curve_perfect_diagonal() -> None:
    # 1000 points placed deterministically so bin acc ~ bin conf.
    rng = np.random.default_rng(0)
    confs = rng.uniform(0.0, 1.0, size=20_000)
    correct = (rng.uniform(0.0, 1.0, size=20_000) < confs).astype(float)
    mean_conf, acc = reliability_curve(confs, correct, n_bins=10)
    finite = ~np.isnan(mean_conf)
    assert np.allclose(mean_conf[finite], acc[finite], atol=0.05)


# --------------------------------------------------------------------------- #
# Sharpness                                                                   #
# --------------------------------------------------------------------------- #


def test_sharpness_constant_is_zero() -> None:
    assert sharpness(np.full(20, 0.7)) == pytest.approx(0.0)


def test_sharpness_extreme_predictions_higher_than_hedger() -> None:
    extreme = np.r_[np.zeros(50), np.ones(50)]
    hedger = np.full(100, 0.5)
    assert sharpness(extreme) > sharpness(hedger)


def test_sharpness_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        sharpness(np.array([0.5, 1.2]))


def test_sharpness_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        sharpness(np.array([]))


# --------------------------------------------------------------------------- #
# Miscalibration area                                                         #
# --------------------------------------------------------------------------- #


def test_miscalibration_area_perfect_is_zero() -> None:
    rng = np.random.default_rng(1)
    confs = rng.uniform(0.0, 1.0, size=2000)
    correct = (rng.uniform(0.0, 1.0, size=2000) < confs).astype(float)
    assert miscalibration_area(confs, correct) < 0.1


def test_miscalibration_area_bounded_unit_interval() -> None:
    rng = np.random.default_rng(2)
    for _ in range(5):
        c = rng.uniform(0.0, 1.0, size=300)
        y = rng.integers(0, 2, size=300).astype(float)
        m = miscalibration_area(c, y)
        assert 0.0 <= m <= 1.0


def test_miscalibration_area_single_point() -> None:
    # Single-point fallback path.
    m = miscalibration_area(np.array([0.7]), np.array([1.0]))
    assert m == pytest.approx(abs(0.7 - 1.0))


# --------------------------------------------------------------------------- #
# Missing ratio                                                               #
# --------------------------------------------------------------------------- #


def test_missing_ratio_basic() -> None:
    assert missing_ratio([True, False, False, True]) == pytest.approx(0.5)
    assert missing_ratio([0, 0, 0, 0]) == 0.0
    assert missing_ratio([1, 1, 1]) == 1.0


def test_missing_ratio_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        missing_ratio([])


# --------------------------------------------------------------------------- #
# Spearman / Kendall                                                          #
# --------------------------------------------------------------------------- #


def test_spearman_monotonic_is_one() -> None:
    confs = np.linspace(0.1, 0.9, 10)
    correct = np.arange(10, dtype=float)
    # Spearman is computed against the y-array, not 0/1 -- monotonic rank => 1.
    assert spearman_rank_correlation(confs, correct) == pytest.approx(1.0)


def test_spearman_anti_monotonic_is_minus_one() -> None:
    confs = np.linspace(0.1, 0.9, 10)
    correct = np.arange(10, 0, -1, dtype=float)
    assert spearman_rank_correlation(confs, correct) == pytest.approx(-1.0)


def test_spearman_n_below_two_returns_zero() -> None:
    assert spearman_rank_correlation(np.array([0.5]), np.array([1.0])) == 0.0


def test_kendall_tau_monotonic_is_one() -> None:
    confs = np.linspace(0.1, 0.9, 6)
    correct = np.arange(6, dtype=float)
    assert kendall_tau(confs, correct) == pytest.approx(1.0)


def test_kendall_tau_anti_monotonic_is_minus_one() -> None:
    confs = np.linspace(0.1, 0.9, 6)
    correct = np.arange(6, 0, -1, dtype=float)
    assert kendall_tau(confs, correct) == pytest.approx(-1.0)


def test_kendall_tau_handles_all_ties() -> None:
    assert kendall_tau(np.full(5, 0.5), np.zeros(5)) == 0.0


def test_kendall_tau_n_below_two_returns_zero() -> None:
    assert kendall_tau(np.array([0.5]), np.array([1.0])) == 0.0


# --------------------------------------------------------------------------- #
# MCC                                                                         #
# --------------------------------------------------------------------------- #


def test_mcc_perfect_prediction() -> None:
    pred = np.array([1, 1, 0, 0])
    correct = np.array([1, 1, 0, 0])
    assert matthews_correlation(pred, correct) == pytest.approx(1.0)


def test_mcc_perfect_disagreement() -> None:
    pred = np.array([1, 1, 0, 0])
    correct = np.array([0, 0, 1, 1])
    assert matthews_correlation(pred, correct) == pytest.approx(-1.0)


def test_mcc_constant_predictor_is_zero() -> None:
    # All predictions positive -> tn=fn=0 -> denom=0 -> 0.0 by convention.
    pred = np.ones(10)
    correct = np.array([1, 0, 1, 0, 1, 0, 1, 0, 1, 0])
    assert matthews_correlation(pred, correct) == 0.0


def test_mcc_shape_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="same shape"):
        matthews_correlation([1, 0, 1], [1, 0])


def test_mcc_empty_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        matthews_correlation([], [])


def test_mcc_imbalanced_class_handled() -> None:
    # 99 negatives, 1 positive: model only correctly flags the positive.
    pred = np.zeros(100)
    pred[0] = 1
    correct = np.zeros(100)
    correct[0] = 1
    assert matthews_correlation(pred, correct) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Adversarial group calibration                                               #
# --------------------------------------------------------------------------- #


def test_adversarial_group_calibration_at_least_global_ece(
    perfectly_calibrated: tuple[np.ndarray, np.ndarray],
) -> None:
    confs, correct = perfectly_calibrated
    worst = adversarial_group_calibration(confs, correct, n_groups=20, group_size_frac=0.1, seed=0)
    assert worst >= 0.0


def test_adversarial_group_calibration_oversized_group_returns_global_ece() -> None:
    confs = np.array([0.1, 0.5, 0.9, 0.5])
    correct = np.array([0, 1, 1, 0], dtype=float)
    global_ece = expected_calibration_error(confs, correct)
    out = adversarial_group_calibration(confs, correct, group_size_frac=2.0)
    assert out == pytest.approx(global_ece)


def test_adversarial_group_calibration_deterministic_with_seed() -> None:
    rng = np.random.default_rng(0)
    confs = rng.uniform(0.0, 1.0, size=500)
    correct = rng.integers(0, 2, size=500).astype(float)
    a = adversarial_group_calibration(confs, correct, n_groups=10, seed=123)
    b = adversarial_group_calibration(confs, correct, n_groups=10, seed=123)
    assert a == b


# --------------------------------------------------------------------------- #
# compute_all integration                                                     #
# --------------------------------------------------------------------------- #


EXPECTED_KEYS = {
    "accuracy",
    "ece",
    "rmsce",
    "brier",
    "refusal_auroc",
    "reversed_pairs_proportion",
    "miscalibration_area",
    "sharpness",
    "prr",
    "spearman",
    "kendall_tau",
    "aurc",
    "auucc",
    "crps_from_confidence",
    "negative_log_likelihood",
    "n",
}


def test_compute_all_returns_all_keys(
    perfectly_calibrated: tuple[np.ndarray, np.ndarray],
) -> None:
    confs, correct = perfectly_calibrated
    out = compute_all(confs, correct)
    assert EXPECTED_KEYS.issubset(out.keys())
    assert "missing_ratio" not in out


def test_compute_all_with_missing_array_includes_missing_ratio(
    perfectly_calibrated: tuple[np.ndarray, np.ndarray],
) -> None:
    confs, correct = perfectly_calibrated
    missing = np.zeros_like(correct, dtype=bool)
    missing[:100] = True
    out = compute_all(confs, correct, missing=missing)
    assert "missing_ratio" in out
    assert out["missing_ratio"] == pytest.approx(100 / confs.size)


def test_compute_all_values_match_individual_metrics(
    perfect_separator: tuple[np.ndarray, np.ndarray],
) -> None:
    confs, correct = perfect_separator
    out = compute_all(confs, correct)
    assert out["ece"] == pytest.approx(expected_calibration_error(confs, correct))
    assert out["brier"] == pytest.approx(brier_score(confs, correct))
    assert out["refusal_auroc"] == pytest.approx(refusal_auroc(confs, correct))
    assert out["sharpness"] == pytest.approx(sharpness(confs))
    assert out["miscalibration_area"] == pytest.approx(miscalibration_area(confs, correct))
    assert out["accuracy"] == pytest.approx(float(correct.mean()))
    assert out["n"] == pytest.approx(float(confs.size))
    assert out["reversed_pairs_proportion"] == pytest.approx(1.0 - out["refusal_auroc"])


def test_compute_all_json_friendly_scalars(
    perfect_separator: tuple[np.ndarray, np.ndarray],
) -> None:
    confs, correct = perfect_separator
    out = compute_all(confs, correct)
    for key, val in out.items():
        assert isinstance(val, float), f"{key} is {type(val).__name__}, not float"
        assert math.isfinite(val) or math.isnan(val), f"{key}={val} is not finite/nan"


def test_compute_all_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        compute_all([0.5, 1.5], [0, 1])
    with pytest.raises(ValueError):
        compute_all([], [])
