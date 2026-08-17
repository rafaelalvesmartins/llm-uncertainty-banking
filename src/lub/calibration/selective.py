# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Selective-prediction metrics: risk-coverage curve and PRR.

Adds the metric family that every UQ literature reviewer looks for
first. ``expected_calibration_error`` and ``brier_score`` measure how
well confidences match accuracies; ``prediction_rejection_ratio``
measures how useful the confidences are for *selectively* producing
answers — i.e. how well the estimator knows when to refuse.

The risk-coverage curve and the Prediction-Rejection Ratio (PRR) are
standard selective-prediction tools, with foundations in Chow (1957)
on optimum character-recognition with a reject option. See El-Yaniv &
Wiener (2010), Geifman & El-Yaniv (2017), and the UQ-for-LLMs literature
surveyed in LM-Polygraph (Fadeeva et al. 2023). The numerics here are pure numpy
— no sklearn, no torch, no external ranker — so this module audits
in under 100 lines.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray

from lub.calibration._utils import _as_pair, _trapezoid


def risk_coverage_curve(
    confs: ArrayLike,
    correct: ArrayLike,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return ``(coverage, risk)`` arrays for the risk-coverage curve.

    The curve sweeps the refusal threshold from "refuse nothing" (full
    coverage, base risk) down to "keep only the most confident prediction"
    (minimum coverage, risk ∈ {0, 1}). Each step drops the least-confident
    remaining example.

    Parameters
    ----------
    confs : array-like of shape (n,)
        Confidence scores in ``[0, 1]``.
    correct : array-like of shape (n,)
        Binary correctness indicators (1 = correct, 0 = incorrect).

    Returns
    -------
    coverage : ndarray of shape (n,)
        Fraction of examples retained at each threshold, from ``1/n`` to 1.
    risk : ndarray of shape (n,)
        Error rate among retained examples at each threshold.
    """
    c, y = _as_pair(confs, correct)
    order = np.argsort(-c, kind="mergesort")  # descending by confidence
    y_sorted = y[order]

    n = int(y_sorted.size)
    cum_correct = np.cumsum(y_sorted)
    kept = np.arange(1, n + 1, dtype=np.float64)
    coverage = kept / n
    risk = 1.0 - cum_correct / kept
    return coverage, risk


def area_under_risk_coverage(
    confs: ArrayLike,
    correct: ArrayLike,
) -> float:
    """Integrate the risk-coverage curve via the trapezoidal rule.

    Lower is better. The area is a cheap scalar summary of the whole
    curve; for head-to-head comparisons prefer :func:`prediction_rejection_ratio`.
    """
    coverage, risk = risk_coverage_curve(confs, correct)
    # Trapezoidal area under risk vs coverage.
    return float(_trapezoid(risk, coverage))


def _optimal_risk_coverage(y: NDArray[np.float64]) -> NDArray[np.float64]:
    """Risk under the oracle ordering (all correct answers first)."""
    n = int(y.size)
    y_sorted = -np.sort(-y)  # 1s first, then 0s
    cum_correct = np.cumsum(y_sorted)
    kept = np.arange(1, n + 1, dtype=np.float64)
    return 1.0 - cum_correct / kept


def prediction_rejection_ratio(
    confs: ArrayLike,
    correct: ArrayLike,
) -> float:
    """Prediction-Rejection Ratio (PRR).

    Defined in Malinin & Gales (2021) as a normalized area that
    compares the estimator's risk-coverage curve to both the oracle
    (all correct answers first) and the random baseline. PRR is
    scale-free in ``[0, 1]``, higher is better, and ``1.0`` means the
    estimator's ranking matches the oracle.

    Implementation: we compute the area between the random curve and
    the estimator curve, divided by the area between the random curve
    and the oracle curve. All three areas are integrated over
    coverage via the trapezoidal rule.
    """
    c, y = _as_pair(confs, correct)
    n = int(y.size)
    if n < 2:
        return 0.0

    coverage = np.arange(1, n + 1, dtype=np.float64) / n
    base_acc = float(y.mean())
    random_risk = np.full(n, 1.0 - base_acc, dtype=np.float64)

    _, estimator_risk = risk_coverage_curve(c, y)
    oracle_risk = _optimal_risk_coverage(y)

    area_estimator = float(_trapezoid(random_risk - estimator_risk, coverage))
    area_oracle = float(_trapezoid(random_risk - oracle_risk, coverage))
    if area_oracle <= 0.0:
        return 0.0
    ratio = area_estimator / area_oracle
    return float(max(min(ratio, 1.0), 0.0))


__all__: Sequence[str] = (
    "area_under_risk_coverage",
    "prediction_rejection_ratio",
    "risk_coverage_curve",
)
