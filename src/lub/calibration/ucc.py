# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Uncertainty Characteristics Curve (UCC) and AUUCC metric.

The UCC (Ghosh et al., IBM UQ360) is a decision-theoretic curve that
plots the fraction of examples whose uncertainty exceeds a threshold
(x-axis) against the accuracy on the *retained* set (y-axis) as the
threshold sweeps from 0 to 1. A perfect estimator has a UCC that hugs
the top-left corner (high accuracy is maintained even when discarding
very few examples). AUUCC (area under the UCC) summarizes the quality
of the uncertainty signal across all possible refusal thresholds.

Pure numpy. No sklearn, no torch.

Reference:
    Ghosh, S., et al. (2021). *Uncertainty Characteristics Curves: A
    Systematic Assessment of Prediction Intervals.* NeurIPS 2021
    Workshop on Distribution-Free Uncertainty Quantification.
    IBM UQ360: https://github.com/IBM/uncertainty-quantification-360
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

from lub.calibration._utils import _trapezoid


def uncertainty_characteristics_curve(
    confs: ArrayLike,
    correct: ArrayLike,
    n_thresholds: int = 100,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Compute the UCC: ``(coverage_fractions, accuracies_on_retained)``.

    Parameters
    ----------
    confs : array-like of float in [0, 1]
        Model confidence for each example.
    correct : array-like of bool / {0, 1}
        Whether each example was answered correctly.
    n_thresholds : int
        Number of confidence thresholds to sweep (evenly spaced on [0, 1]).

    Returns
    -------
    coverage, accuracy : (N,) arrays
        ``coverage[i]`` = fraction of examples with confidence ≥ threshold[i].
        ``accuracy[i]`` = accuracy on the retained set at that threshold.
        Both are NaN when no examples are retained.
    """
    c = np.asarray(confs, dtype=np.float64).ravel()
    y = np.asarray(correct, dtype=np.float64).ravel()
    if c.shape != y.shape:
        raise ValueError("confs and correct must have same shape")
    if c.size == 0:
        raise ValueError("inputs must be non-empty")

    thresholds = np.linspace(0.0, 1.0, n_thresholds)
    n = c.size
    coverage = np.empty(n_thresholds, dtype=np.float64)
    accuracy = np.full(n_thresholds, np.nan, dtype=np.float64)

    for i, th in enumerate(thresholds):
        mask = c >= th
        count = int(mask.sum())
        coverage[i] = count / n
        if count > 0:
            accuracy[i] = float(y[mask].mean())
    return coverage, accuracy


def auucc(confs: ArrayLike, correct: ArrayLike, n_thresholds: int = 100) -> float:
    """Area Under the Uncertainty Characteristics Curve.

    Higher is better: an estimator whose confidence perfectly separates
    correct from incorrect achieves AUUCC close to the product of mean
    accuracy and mean coverage, while a random estimator's AUUCC equals
    the base-rate accuracy.
    """
    coverage, accuracy = uncertainty_characteristics_curve(confs, correct, n_thresholds)
    valid = ~np.isnan(accuracy)
    if not valid.any():
        return 0.0
    return float(_trapezoid(accuracy[valid], coverage[valid]))


__all__ = [
    "auucc",
    "uncertainty_characteristics_curve",
]
