# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Pure-numpy calibration metrics.

All functions take two 1-D array-likes of identical length:

* ``confs``    -- model confidences in ``[0, 1]`` (float)
* ``correct``  -- ground-truth correctness indicators in ``{0, 1}`` (bool/int)

Returned scalars are plain ``float`` for JSON-friendliness. No sklearn, no
torch -- callers in regulated environments should be able to audit this file
end-to-end without pulling heavy ML stacks.

Table of contents
-----------------

Helpers (private):
    _as_pair, _bin_indices, _bin_aggregates, _rankdata

Calibration metrics:
    expected_calibration_error       -- ECE (Guo et al. 2017)
    root_mean_squared_calibration_error -- RMSCE (Nguyen and O'Connor 2015)
    expected_normalized_calibration_error -- ENCE (Levi et al. 2022)
    brier_score                      -- mean squared error of forecasts
    miscalibration_area              -- bin-free CDF-based alternative to ECE
    reliability_curve                -- per-bin (mean_conf, accuracy) arrays
    sharpness                        -- spread of the confidence distribution

Ranking / discrimination metrics:
    refusal_auroc                    -- AUROC of confidence as refusal signal
    reversed_pairs_proportion        -- 1 - refusal_auroc (error-rate form)
    spearman_rank_correlation        -- Spearman rho(confs, correct)
    kendall_tau                      -- Kendall tau(confs, correct)
    matthews_correlation             -- MCC for binary classification

Robustness metrics:
    adversarial_group_calibration    -- worst-case ECE over random subgroups

Utilities:
    missing_ratio                    -- fraction flagged as missing/refused
    compute_all                      -- convenience bundle for BenchmarkRunner
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray

from lub.calibration._utils import _as_pair as _as_pair
from lub.calibration._utils import (
    _trapezoid as _trapezoid,  # re-export for callers that previously reached into metrics.py
)


def _bin_indices(c: NDArray[np.float64], n_bins: int) -> NDArray[np.intp]:
    # np.digitize returns 1..n_bins for interior points; clip to [0, n_bins-1].
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    return np.clip(np.digitize(c, edges[1:-1], right=False), 0, n_bins - 1).astype(np.intp)


def _bin_aggregates(
    c: NDArray[np.float64],
    y: NDArray[np.float64],
    n_bins: int,
) -> tuple[NDArray[np.intp], NDArray[np.float64], NDArray[np.float64]]:
    """Return per-bin ``(counts, sum_conf, sum_correct)`` via a single pass."""
    if n_bins < 1:
        raise ValueError(f"n_bins must be >= 1, got {n_bins}")
    bin_idx = _bin_indices(c, n_bins)
    counts = np.bincount(bin_idx, minlength=n_bins)
    sum_conf = np.bincount(bin_idx, weights=c, minlength=n_bins).astype(np.float64)
    sum_correct = np.bincount(bin_idx, weights=y, minlength=n_bins).astype(np.float64)
    return counts, sum_conf, sum_correct


def expected_calibration_error(
    confs: ArrayLike,
    correct: ArrayLike,
    n_bins: int = 15,
) -> float:
    """Expected Calibration Error (Guo et al. 2017) with equal-width bins.

    ECE = sum_b (|B_b| / N) * |acc(B_b) - conf(B_b)|
    """
    c, y = _as_pair(confs, correct)
    counts, sum_conf, sum_correct = _bin_aggregates(c, y, n_bins)
    nonempty = counts > 0
    if not nonempty.any():
        return 0.0
    mean_conf = np.zeros_like(sum_conf)
    acc = np.zeros_like(sum_correct)
    mean_conf[nonempty] = sum_conf[nonempty] / counts[nonempty]
    acc[nonempty] = sum_correct[nonempty] / counts[nonempty]
    weights = counts / c.size
    return float(np.sum(weights * np.abs(acc - mean_conf)))


def root_mean_squared_calibration_error(
    confs: ArrayLike,
    correct: ArrayLike,
    n_bins: int = 15,
) -> float:
    """RMSCE -- L2 analogue of ECE.

    RMSCE = sqrt( sum_b (|B_b| / N) * (acc(B_b) - conf(B_b))^2 )

    Differs from :func:`expected_calibration_error` by squaring the
    per-bin error before averaging, then taking the root. This
    penalizes bins with large calibration gaps more heavily than ECE
    does, which is useful when a small fraction of predictions are
    badly miscalibrated but the rest are fine -- ECE can hide that;
    RMSCE surfaces it.

    Reference: Nguyen and O'Connor 2015, "Posterior calibration and
    exploratory analysis for natural language processing models."
    """
    c, y = _as_pair(confs, correct)
    counts, sum_conf, sum_correct = _bin_aggregates(c, y, n_bins)
    nonempty = counts > 0
    if not nonempty.any():
        return 0.0
    mean_conf = np.zeros_like(sum_conf)
    acc = np.zeros_like(sum_correct)
    mean_conf[nonempty] = sum_conf[nonempty] / counts[nonempty]
    acc[nonempty] = sum_correct[nonempty] / counts[nonempty]
    weights = counts / c.size
    squared_gap = (acc - mean_conf) ** 2
    return float(math.sqrt(float(np.sum(weights * squared_gap))))


def expected_normalized_calibration_error(
    confs: ArrayLike,
    correct: ArrayLike,
    n_bins: int = 15,
) -> float:
    """ENCE -- per-bin RMSE normalized by the bin's mean confidence.

    For each non-empty bin:

        bin_term = sqrt((acc - conf)^2) / conf

    then weighted-average across bins by bin mass. Bins with mean
    confidence == 0 contribute zero (they cannot be miscalibrated in
    the normalized sense).

    ENCE was introduced for regression calibration (Levi et al. 2022,
    "Evaluating and Calibrating Uncertainty Prediction in Regression
    Tasks"), where it normalizes by the predicted standard deviation.
    For the classification/confidence case used by LUB we normalize
    by the bin mean confidence, which is the conventional adaptation.

    Why it matters in regulated banking: a calibration gap of 0.02 on
    a high-confidence bin (conf = 0.95) and on a low-confidence bin
    (conf = 0.10) are treated identically by ECE, but ENCE weights
    the latter as 10x more serious. In model-risk review, over-confidence
    on low-confidence claims is usually the more consequential failure.
    """
    c, y = _as_pair(confs, correct)
    counts, sum_conf, sum_correct = _bin_aggregates(c, y, n_bins)
    nonempty = counts > 0
    if not nonempty.any():
        return 0.0
    mean_conf = np.zeros_like(sum_conf)
    acc = np.zeros_like(sum_correct)
    mean_conf[nonempty] = sum_conf[nonempty] / counts[nonempty]
    acc[nonempty] = sum_correct[nonempty] / counts[nonempty]
    weights = counts / c.size

    per_bin = np.zeros_like(mean_conf)
    safe = nonempty & (mean_conf > 0.0)
    per_bin[safe] = np.sqrt((acc[safe] - mean_conf[safe]) ** 2) / mean_conf[safe]
    return float(np.sum(weights * per_bin))


def brier_score(confs: ArrayLike, correct: ArrayLike) -> float:
    """Brier score: mean squared error between confidence and correctness."""
    c, y = _as_pair(confs, correct)
    return float(np.mean((c - y) ** 2))


def refusal_auroc(confs: ArrayLike, correct: ArrayLike) -> float:
    """AUROC of confidence as a score for predicting correctness.

    Implemented via the rank-sum identity, scipy-free, with a vectorized
    tie-group handler:

        AUROC = (R_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)

    Returns ``0.5`` if either class is absent (undefined AUROC).
    """
    c, y = _as_pair(confs, correct)
    pos = y > 0.5
    n_pos = int(pos.sum())
    n_neg = int(y.size - n_pos)
    if n_pos == 0 or n_neg == 0:
        return 0.5

    order = np.argsort(c, kind="mergesort")
    sorted_c = c[order]
    sorted_pos = pos[order]

    # Average ranks with tie handling, fully vectorized:
    # 1. Mark tie-group boundaries on the sorted values.
    n = c.size
    boundaries = np.empty(n + 1, dtype=bool)
    boundaries[0] = True
    boundaries[-1] = True
    boundaries[1:-1] = sorted_c[1:] != sorted_c[:-1]
    starts = np.flatnonzero(boundaries[:-1])
    ends = np.flatnonzero(boundaries[1:]) + 1  # exclusive
    # 2. Each tie group gets the average of its 1-indexed rank positions.
    group_ranks = 0.5 * (starts + ends + 1)
    ranks = np.repeat(group_ranks, ends - starts)

    r_pos = float(ranks[sorted_pos].sum())
    return float((r_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def reliability_curve(
    confs: ArrayLike,
    correct: ArrayLike,
    n_bins: int = 15,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return per-bin ``(mean_confidence, empirical_accuracy)``.

    Empty bins are returned as ``nan`` so the caller can decide whether to
    drop or interpolate them when plotting.
    """
    c, y = _as_pair(confs, correct)
    counts, sum_conf, sum_correct = _bin_aggregates(c, y, n_bins)
    nonempty = counts > 0
    mean_conf = np.full(n_bins, np.nan, dtype=np.float64)
    acc = np.full(n_bins, np.nan, dtype=np.float64)
    mean_conf[nonempty] = sum_conf[nonempty] / counts[nonempty]
    acc[nonempty] = sum_correct[nonempty] / counts[nonempty]
    return mean_conf, acc


def sharpness(confs: ArrayLike) -> float:
    """Standard deviation of confidence predictions.

    Gneiting and Raftery (2007): a "sharp" estimator commits to decisive
    predictions near 0 or 1, while a "timid" one hedges near 0.5.
    Sharpness alone is meaningless -- a miscalibrated estimator can be
    arbitrarily sharp by always answering 1.0 -- but combined with a
    calibration metric it is the standard way to distinguish
    well-calibrated confident estimators from well-calibrated hedgers.
    """
    c = np.asarray(confs, dtype=np.float64).ravel()
    if c.size == 0:
        raise ValueError("confs must be non-empty")
    if np.any((c < 0.0) | (c > 1.0)):
        raise ValueError("confs must lie in [0, 1]")
    return float(np.std(c))


def miscalibration_area(
    confs: ArrayLike,
    correct: ArrayLike,
) -> float:
    """Area between the sorted calibration curve and the diagonal.

    Bin-free alternative to ECE. Examples are sorted by confidence,
    then ``|cumulative_conf - cumulative_correct|`` is integrated over
    the normalized index via the trapezoidal rule. Lower is better,
    ``0`` is perfect calibration. Unlike
    :func:`expected_calibration_error` this is insensitive to bin-edge
    placement, which matters when the confidence distribution is
    concentrated near 0 or 1 (common for overconfident LLMs).

    Matches the convention of ``uncertainty_toolbox.metrics_calibration
    .miscalibration_area`` up to normalization.
    """
    c, y = _as_pair(confs, correct)
    n = c.size
    order = np.argsort(c, kind="mergesort")
    cum_conf = np.cumsum(c[order]) / n
    cum_correct = np.cumsum(y[order]) / n
    if n == 1:
        return float(abs(cum_conf[0] - cum_correct[0]))
    x = np.linspace(0.0, 1.0, n)
    # Raw integral tops out near 0.5 for all-wrong; multiply by 2 so
    # the metric lives in [0, 1] with 1 = worst possible.
    raw = float(_trapezoid(np.abs(cum_conf - cum_correct), x))
    return min(1.0, 2.0 * raw)


def missing_ratio(missing: ArrayLike) -> float:
    """Fraction of predictions flagged as missing / refused / unparseable.

    Important banking-specific signal: an LLM that refuses to answer or
    returns an unparseable response is not the same as a wrong answer,
    and SR 11-7 model risk reviewers want the abstention rate reported
    separately from accuracy. The convention follows the PIXIU/FLARE
    financial benchmark suite (Xie et al. 2023), where a "missing" item
    is one whose response does not match any allowed option or
    expected format.

    Parameters
    ----------
    missing : array-like of shape (n,)
        Boolean or 0/1 array. ``True`` = missing/refused/unparseable.
    """
    m = np.asarray(missing).ravel()
    if m.size == 0:
        raise ValueError("missing must be non-empty")
    return float(np.asarray(m, dtype=bool).mean())


def compute_all(
    confs: ArrayLike,
    correct: ArrayLike,
    n_bins: int = 15,
    missing: ArrayLike | None = None,
) -> dict[str, float]:
    """Convenience bundle of all calibration metrics.

    Returns a dict with keys: ``accuracy``, ``ece``, ``rmsce``,
    ``brier``, ``refusal_auroc``, ``reversed_pairs_proportion``,
    ``miscalibration_area``, ``sharpness``, ``prr``, ``spearman``,
    ``kendall_tau``, ``aurc``, ``auucc``, ``crps_from_confidence``,
    ``negative_log_likelihood``, ``n``; and (when ``missing`` is
    provided) ``missing_ratio``. Used by
    :class:`lub.benchmarks.runner.BenchmarkRunner` to populate
    :class:`lub.types.BenchmarkResult`. Validates inputs once, then
    dispatches to the underlying metrics on already-validated arrays.
    """
    c, y = _as_pair(confs, correct)
    counts, sum_conf, sum_correct = _bin_aggregates(c, y, n_bins)
    nonempty = counts > 0

    if nonempty.any():
        mean_conf_nz = sum_conf[nonempty] / counts[nonempty]
        acc_nz = sum_correct[nonempty] / counts[nonempty]
        weights = counts[nonempty] / c.size
        ece = float(np.sum(weights * np.abs(acc_nz - mean_conf_nz)))
    else:
        ece = 0.0

    from lub.calibration.scoring_rules import crps_from_confidence, negative_log_likelihood
    from lub.calibration.selective import area_under_risk_coverage, prediction_rejection_ratio
    from lub.calibration.ucc import auucc

    if nonempty.any():
        mean_conf_all = np.zeros_like(sum_conf)
        acc_all = np.zeros_like(sum_correct)
        mean_conf_all[nonempty] = sum_conf[nonempty] / counts[nonempty]
        acc_all[nonempty] = sum_correct[nonempty] / counts[nonempty]
        weights_all = counts / c.size
        rmsce = float(np.sqrt(np.sum(weights_all * (acc_all - mean_conf_all) ** 2)))
    else:
        rmsce = 0.0

    auroc = refusal_auroc(c, y)
    out: dict[str, float] = {
        "accuracy": float(y.mean()),
        "ece": ece,
        "rmsce": rmsce,
        "brier": float(np.mean((c - y) ** 2)),
        "refusal_auroc": auroc,
        "reversed_pairs_proportion": 1.0 - auroc,
        "miscalibration_area": miscalibration_area(c, y),
        "sharpness": sharpness(c),
        "prr": prediction_rejection_ratio(c, y),
        "spearman": spearman_rank_correlation(c, y),
        "kendall_tau": kendall_tau(c, y),
        "aurc": area_under_risk_coverage(c, y),
        "auucc": auucc(c, y),
        "crps_from_confidence": crps_from_confidence(c, y),
        "negative_log_likelihood": negative_log_likelihood(c, y),
        "n": float(c.size),
    }
    if missing is not None:
        out["missing_ratio"] = missing_ratio(missing)
    return out


def _rankdata(x: NDArray[np.float64]) -> NDArray[np.float64]:
    """Average-rank assignment (scipy-free)."""
    order = np.argsort(x, kind="mergesort")
    sorted_x = x[order]
    n = x.size
    ranks = np.empty(n, dtype=np.float64)
    i = 0
    while i < n:
        j = i + 1
        while j < n and sorted_x[j] == sorted_x[i]:
            j += 1
        ranks[i:j] = 0.5 * (i + 1 + j)
        i = j
    result = np.empty(n, dtype=np.float64)
    result[order] = ranks
    return result


def spearman_rank_correlation(confs: ArrayLike, correct: ArrayLike) -> float:
    """Spearman rank correlation between confidence and correctness.

    SR 11-7 model validation reports expect rank-order correlation alongside ECE and AUROC.
    Returns a value in [-1, 1].

    Spearman IS Pearson applied to the (tie-corrected, average) ranks. This function used to
    compute those average ranks with :func:`_rankdata` and then discard them, applying the
    shortcut ``1 - 6*sum(d^2)/(n*(n^2-1))`` instead — which is exact ONLY when there are no
    ties. ``correct`` is a binary {0,1} vector, so ties are *guaranteed*: the shortcut was
    systematically wrong on every benchmark, and it invented a confident-looking ``0.5`` on
    all-correct / all-wrong runs where the correlation is in fact undefined. The value flows
    through :func:`compute_all` into the SR 11-7 / NIST AI RMF reports, so a validator
    recomputing it with scipy would not have matched the number lub reported.

    Constant input (no variance in either vector) → ``0.0``: there is no rank-order
    relationship to measure. Consistent with the ``n < 2`` case, and never a fabricated value.
    """
    c, y = _as_pair(confs, correct)
    n = c.size
    if n < 2:
        return 0.0
    rc = _rankdata(c)
    ry = _rankdata(y)
    # Pearson on the ranks (the definition) — tie-safe, unlike the d^2 shortcut.
    dc = rc - rc.mean()
    dy = ry - ry.mean()
    denom = float(np.sqrt(float(np.sum(dc * dc)) * float(np.sum(dy * dy))))
    if denom == 0.0:
        return 0.0  # constant confidences or constant correctness → undefined; report no signal
    return float(np.sum(dc * dy) / denom)


def kendall_tau(confs: ArrayLike, correct: ArrayLike) -> float:
    """Kendall tau-b rank correlation between confidence and correctness.

    Handles ties via the tau-b correction. Returns a value in [-1, 1].
    """
    c, y = _as_pair(confs, correct)
    n = c.size
    if n < 2:
        return 0.0
    concordant = 0
    discordant = 0
    ties_c = 0
    ties_y = 0
    for i in range(n):
        for j in range(i + 1, n):
            dc = c[i] - c[j]
            dy = y[i] - y[j]
            if dc == 0.0 and dy == 0.0:
                ties_c += 1
                ties_y += 1
            elif dc == 0.0:
                ties_c += 1
            elif dy == 0.0:
                ties_y += 1
            elif (dc > 0 and dy > 0) or (dc < 0 and dy < 0):
                concordant += 1
            else:
                discordant += 1
    n_pairs = n * (n - 1) // 2
    denom = math.sqrt(float(n_pairs - ties_c) * float(n_pairs - ties_y))
    if denom == 0.0:
        return 0.0
    return float((concordant - discordant) / denom)


def adversarial_group_calibration(
    confs: ArrayLike,
    correct: ArrayLike,
    n_groups: int = 100,
    group_size_frac: float = 0.1,
    seed: int = 0,
) -> float:
    """Worst-case ECE across random subgroups (Zhao et al. 2021).

    Samples ``n_groups`` random subsets of size ``group_size_frac * N``,
    computes ECE on each, and returns the maximum. Addresses NIST
    MEASURE 2.6 (bias testing) and BCB Resolution 4966 fairness.
    """
    c, y = _as_pair(confs, correct)
    n = c.size
    group_size = max(int(n * group_size_frac), 2)
    if group_size > n:
        return expected_calibration_error(c, y)
    rng = np.random.RandomState(seed)
    worst = 0.0
    for _ in range(n_groups):
        idx = rng.choice(n, size=group_size, replace=False)
        ece = expected_calibration_error(c[idx], y[idx], n_bins=max(group_size // 5, 2))
        if ece > worst:
            worst = ece
    return float(worst)


def matthews_correlation(pred: ArrayLike, correct: ArrayLike) -> float:
    """Matthews Correlation Coefficient for binary classification.

    Standard in credit-risk and fraud-detection model validation --
    bank model-risk teams report MCC alongside accuracy/AUROC because
    it is robust under severe class imbalance (common for fraud and
    default prediction, where the positive class is often <1%).

    Inputs are binary ``{0, 1}`` arrays, not confidences:

    - ``pred``     -- predicted class (0 = negative, 1 = positive)
    - ``correct``  -- ground-truth class

    Returns a value in ``[-1, 1]``. ``1`` is perfect agreement,
    ``0`` is no better than random, ``-1`` is perfect disagreement.
    Returns ``0.0`` when any row or column of the confusion matrix is
    entirely zero (Matthews 1975; Chicco and Jurman 2020 for the
    degenerate-case convention).

    Reference: Matthews (1975), "Comparison of the predicted and
    observed secondary structure of T4 phage lysozyme", BBA 405(2).
    PIXIU / FinBen benchmarks (Feng et al. 2023) use this as the
    primary metric for credit-risk and fraud tasks.
    """
    p = np.asarray(pred, dtype=np.float64).ravel()
    y = np.asarray(correct, dtype=np.float64).ravel()
    if p.shape != y.shape:
        raise ValueError(f"pred and correct must have same shape, got {p.shape} vs {y.shape}")
    if p.size == 0:
        raise ValueError("pred/correct must be non-empty")
    p_bin = (p > 0.5).astype(np.float64)
    y_bin = (y > 0.5).astype(np.float64)
    tp = float(np.sum((p_bin == 1.0) & (y_bin == 1.0)))
    tn = float(np.sum((p_bin == 0.0) & (y_bin == 0.0)))
    fp = float(np.sum((p_bin == 1.0) & (y_bin == 0.0)))
    fn = float(np.sum((p_bin == 0.0) & (y_bin == 1.0)))
    denom_sq = (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)
    if denom_sq == 0.0:
        return 0.0
    return float((tp * tn - fp * fn) / math.sqrt(denom_sq))


def reversed_pairs_proportion(
    confs: ArrayLike,
    correct: ArrayLike,
) -> float:
    """Reversed Pairs Proportion (RPP).

    Fraction of (correct, incorrect) pairs where the model assigns *higher*
    confidence to the incorrect answer than to the correct one. A perfect
    uncertainty estimator has RPP = 0; random has RPP ~ 0.5.

    Equivalent to ``1 - refusal_auroc`` under the rank-sum definition,
    but interpretable as a direct error rate rather than an area metric.
    """
    auroc = refusal_auroc(confs, correct)
    return float(1.0 - auroc)


__all__: Sequence[str] = (
    "adversarial_group_calibration",
    "brier_score",
    "compute_all",
    "expected_calibration_error",
    "expected_normalized_calibration_error",
    "kendall_tau",
    "matthews_correlation",
    "miscalibration_area",
    "missing_ratio",
    "refusal_auroc",
    "reliability_curve",
    "reversed_pairs_proportion",
    "root_mean_squared_calibration_error",
    "sharpness",
    "spearman_rank_correlation",
)
