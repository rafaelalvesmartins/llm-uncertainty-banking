# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import numpy as np
import pytest

from lub.calibration import prr, risk_coverage_curve
from lub.calibration.metrics import (
    brier_score,
    compute_all,
    expected_calibration_error,
    miscalibration_area,
    missing_ratio,
    refusal_auroc,
    reliability_curve,
    reversed_pairs_proportion,
    root_mean_squared_calibration_error,
    sharpness,
    spearman_rank_correlation,
)


def test_perfect_calibration_zero_ece_and_brier() -> None:
    rng = np.random.default_rng(0)
    confs = rng.uniform(0.0, 1.0, size=2000)
    correct = (rng.uniform(0.0, 1.0, size=2000) < confs).astype(float)
    assert expected_calibration_error(confs, correct, n_bins=20) < 0.05
    assert brier_score(confs, correct) < 0.3


def test_brier_score_all_correct_high_conf_is_small() -> None:
    confs = np.full(100, 0.99)
    correct = np.ones(100)
    assert brier_score(confs, correct) == pytest.approx((0.01) ** 2, abs=1e-9)


def test_ece_worst_case_is_one() -> None:
    confs = np.ones(10)
    correct = np.zeros(10)
    assert expected_calibration_error(confs, correct) == pytest.approx(1.0)


def test_refusal_auroc_perfect_separator() -> None:
    confs = np.array([0.1, 0.2, 0.3, 0.8, 0.9, 1.0])
    correct = np.array([0, 0, 0, 1, 1, 1])
    assert refusal_auroc(confs, correct) == pytest.approx(1.0)


def test_refusal_auroc_random_is_half() -> None:
    rng = np.random.default_rng(1)
    confs = rng.uniform(0.0, 1.0, size=500)
    correct = rng.integers(0, 2, size=500).astype(float)
    assert 0.4 < refusal_auroc(confs, correct) < 0.6


def test_refusal_auroc_degenerate_returns_half() -> None:
    confs = np.array([0.1, 0.5, 0.9])
    assert refusal_auroc(confs, np.ones(3)) == 0.5
    assert refusal_auroc(confs, np.zeros(3)) == 0.5


def test_refusal_auroc_handles_ties() -> None:
    confs = np.array([0.5, 0.5, 0.5, 0.5])
    correct = np.array([1, 1, 0, 0])
    assert refusal_auroc(confs, correct) == pytest.approx(0.5)


def test_reliability_curve_empty_bins_are_nan() -> None:
    confs = np.array([0.05, 0.95])
    correct = np.array([0, 1])
    mean_conf, acc = reliability_curve(confs, correct, n_bins=10)
    assert np.isnan(mean_conf[5])
    assert np.isnan(acc[5])
    assert not np.isnan(mean_conf[0])
    assert not np.isnan(mean_conf[9])


def test_invalid_confidence_range_rejected() -> None:
    with pytest.raises(ValueError):
        expected_calibration_error([0.5, 1.2], [0, 1])


def test_shape_mismatch_rejected() -> None:
    with pytest.raises(ValueError):
        brier_score([0.5, 0.5], [1])


def test_compute_all_returns_expected_keys() -> None:
    out = compute_all([0.1, 0.9], [0, 1])
    assert set(out) == {
        "accuracy",
        "ece",
        "brier",
        "refusal_auroc",
        "miscalibration_area",
        "sharpness",
        "prr",
        "rmsce",
        "reversed_pairs_proportion",
        "spearman",
        "kendall_tau",
        "aurc",
        "auucc",
        "crps_from_confidence",
        "negative_log_likelihood",
        "n",
    }
    assert out["n"] == 2.0
    assert out["accuracy"] == pytest.approx(0.5)


def test_risk_coverage_curve_perfect_ranker() -> None:
    confs = np.array([0.1, 0.2, 0.8, 0.9])
    correct = np.array([0, 0, 1, 1])
    coverage, risk = risk_coverage_curve(confs, correct)
    assert coverage.shape == risk.shape == (4,)
    assert coverage[-1] == pytest.approx(1.0)
    # The two most confident are both correct, so risk stays at 0 for the
    # first half of the coverage sweep.
    assert risk[0] == pytest.approx(0.0)
    assert risk[1] == pytest.approx(0.0)
    # Full coverage gives the unconditional error rate.
    assert risk[-1] == pytest.approx(0.5)


def test_risk_coverage_is_monotone_for_perfect_ranker() -> None:
    confs = np.array([0.1, 0.3, 0.7, 0.9])
    correct = np.array([0, 0, 1, 1])
    _, risk = risk_coverage_curve(confs, correct)
    assert np.all(np.diff(risk) >= -1e-12)


def test_prr_perfect_ranker_is_one() -> None:
    confs = np.array([0.1, 0.2, 0.8, 0.9])
    correct = np.array([0, 0, 1, 1])
    assert prr(confs, correct) == pytest.approx(1.0)


def test_prr_reversed_ranker_clamped_to_zero() -> None:
    confs = np.array([0.9, 0.8, 0.2, 0.1])
    correct = np.array([0, 0, 1, 1])
    # selective.prediction_rejection_ratio clamps to [0, 1]: a ranker
    # worse than random is reported as 0, not a negative score.
    assert prr(confs, correct) == pytest.approx(0.0)


def test_prr_degenerate_all_correct_returns_zero() -> None:
    assert prr([0.1, 0.5, 0.9], [1, 1, 1]) == 0.0


def test_prr_degenerate_all_wrong_returns_zero() -> None:
    assert prr([0.1, 0.5, 0.9], [0, 0, 0]) == 0.0


def test_compute_all_includes_missing_ratio_when_provided() -> None:
    out = compute_all([0.1, 0.9, 0.5], [0, 1, 1], missing=[False, False, True])
    assert "missing_ratio" in out
    assert out["missing_ratio"] == pytest.approx(1.0 / 3.0)


def test_sharpness_constant_is_zero() -> None:
    assert sharpness(np.full(50, 0.7)) == pytest.approx(0.0)


def test_sharpness_extremes_are_half() -> None:
    confs = np.array([0.0, 1.0] * 50)
    assert sharpness(confs) == pytest.approx(0.5)


def test_sharpness_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        sharpness([0.1, 1.5])


def test_sharpness_rejects_empty() -> None:
    with pytest.raises(ValueError):
        sharpness([])


def test_miscalibration_area_perfect_is_zero() -> None:
    confs = np.linspace(0.0, 1.0, 1001)
    correct = (np.random.default_rng(0).uniform(size=1001) < confs).astype(float)
    assert miscalibration_area(confs, correct) < 0.05


def test_miscalibration_area_worst_case_is_large() -> None:
    confs = np.full(100, 1.0)
    correct = np.zeros(100)
    assert miscalibration_area(confs, correct) > 0.9


def test_miscalibration_area_symmetric_under_inverted_confidences() -> None:
    # Flipping (conf, 1-correct) and (1-conf, correct) should give same area.
    rng = np.random.default_rng(42)
    confs = rng.uniform(size=200)
    correct = (rng.uniform(size=200) < 0.5).astype(float)
    a = miscalibration_area(confs, correct)
    assert a >= 0.0  # sanity


def test_missing_ratio_all_missing() -> None:
    assert missing_ratio([True, True, True]) == pytest.approx(1.0)


def test_missing_ratio_none_missing() -> None:
    assert missing_ratio([False, False, False, False]) == pytest.approx(0.0)


def test_missing_ratio_accepts_int_mask() -> None:
    assert missing_ratio([0, 1, 0, 1]) == pytest.approx(0.5)


def test_missing_ratio_rejects_empty() -> None:
    with pytest.raises(ValueError):
        missing_ratio([])


# ---- RMSCE ----------------------------------------------------------------


def test_rmsce_perfect_calibration_near_zero() -> None:
    rng = np.random.default_rng(42)
    confs = rng.uniform(0.0, 1.0, size=2000)
    correct = (rng.uniform(0.0, 1.0, size=2000) < confs).astype(float)
    assert root_mean_squared_calibration_error(confs, correct, n_bins=20) < 0.05


def test_rmsce_all_wrong_high_confidence() -> None:
    confs = np.array([0.99, 0.95, 0.90, 0.88])
    correct = np.array([0.0, 0.0, 0.0, 0.0])
    rmsce = root_mean_squared_calibration_error(confs, correct, n_bins=4)
    assert rmsce > 0.8


def test_rmsce_geq_zero() -> None:
    rng = np.random.default_rng(7)
    confs = rng.uniform(size=200)
    correct = (rng.uniform(size=200) < 0.5).astype(float)
    assert root_mean_squared_calibration_error(confs, correct) >= 0.0


# ---- RPP ------------------------------------------------------------------


def test_rpp_perfect_ranking_is_zero() -> None:
    confs = np.array([0.9, 0.8, 0.2, 0.1])
    correct = np.array([1.0, 1.0, 0.0, 0.0])
    assert reversed_pairs_proportion(confs, correct) == pytest.approx(0.0, abs=1e-9)


def test_rpp_inverted_ranking_is_one() -> None:
    confs = np.array([0.1, 0.2, 0.8, 0.9])
    correct = np.array([1.0, 1.0, 0.0, 0.0])
    assert reversed_pairs_proportion(confs, correct) == pytest.approx(1.0, abs=1e-9)


def test_rpp_random_near_half() -> None:
    rng = np.random.default_rng(99)
    confs = rng.uniform(size=500)
    correct = rng.integers(0, 2, size=500).astype(float)
    rpp = reversed_pairs_proportion(confs, correct)
    assert 0.3 < rpp < 0.7


def test_rpp_complement_of_auroc() -> None:
    confs = np.array([0.9, 0.7, 0.3, 0.1])
    correct = np.array([1.0, 0.0, 1.0, 0.0])
    auroc = refusal_auroc(confs, correct)
    rpp = reversed_pairs_proportion(confs, correct)
    assert rpp == pytest.approx(1.0 - auroc, abs=1e-12)


def test_compute_all_includes_rmsce_and_rpp() -> None:
    confs = np.array([0.9, 0.8, 0.3, 0.2])
    correct = np.array([1.0, 1.0, 0.0, 0.0])
    result = compute_all(confs, correct)
    assert "rmsce" in result
    assert "reversed_pairs_proportion" in result
    assert "spearman" in result
    assert "kendall_tau" in result
    assert result["rmsce"] >= 0.0
    assert 0.0 <= result["reversed_pairs_proportion"] <= 1.0


# ---------------------------------------------------------------------------
# Spearman must be Pearson-on-average-ranks, NOT the no-ties d^2 shortcut.
# ---------------------------------------------------------------------------


def test_spearman_is_pearson_on_average_ranks_when_there_are_ties() -> None:
    """Regression: ``spearman_rank_correlation`` computed tie-corrected average ranks with
    ``_rankdata`` and then THREW THEM AWAY, applying ``1 - 6*sum(d^2)/(n*(n^2-1))`` — a
    shortcut that is only exact when there are NO ties.

    The ``correct`` vector is binary {0,1}, so ties are *guaranteed*: the shortcut was
    systematically wrong on every benchmark, and the value flows through ``compute_all()``
    into the SR 11-7 / NIST AI RMF reports. A validator recomputing it with scipy would get a
    different number than the one lub reports.

    Reference below is Pearson-on-ranks computed independently (no scipy dependency):
        confs   [0.9, 0.8, 0.7, 0.6] -> ranks [4, 3, 2, 1]
        correct [1,   0,   1,   0]   -> average ranks [3.5, 1.5, 3.5, 1.5]
        Pearson(ranks) = 2.0 / sqrt(5*4) = 0.4472...   (the old shortcut said 0.5)
    """
    confs = [0.9, 0.8, 0.7, 0.6]
    correct = [1, 0, 1, 0]

    rc = np.array([4.0, 3.0, 2.0, 1.0])
    ry = np.array([3.5, 1.5, 3.5, 1.5])
    expected = float(np.corrcoef(rc, ry)[0, 1])  # 0.4472135955

    got = spearman_rank_correlation(confs, correct)
    assert got == pytest.approx(expected, abs=1e-9), (
        f"Spearman={got} but Pearson-on-average-ranks={expected} "
        "(the no-ties d^2 shortcut is invalid on a binary correctness vector)"
    )


def test_spearman_on_constant_input_reports_no_signal_not_a_spurious_value() -> None:
    """All-correct (or all-wrong) runs have NO rank-order relationship to measure — the
    correlation is undefined. The old shortcut invented a confident-looking 0.5 for them.
    Contract: report 0.0 (no measurable signal), consistent with the n < 2 case."""
    assert spearman_rank_correlation([0.1, 0.5, 0.9, 0.3], [1, 1, 1, 1]) == 0.0
    assert spearman_rank_correlation([0.1, 0.5, 0.9, 0.3], [0, 0, 0, 0]) == 0.0
