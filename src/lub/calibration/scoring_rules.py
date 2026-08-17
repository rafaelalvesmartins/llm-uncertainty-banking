# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Proper scoring rules for uncertainty evaluation.

Interval Score (Winkler 1972) and CRPS (Gneiting & Raftery 2007) are the
two most-cited proper scoring rules in the UQ literature. Both are pure
numpy — no scipy, no torch.

For LUB's classification-style pipeline (confidence in [0,1], binary
correctness), these functions operate on prediction intervals derived
from conformal sets or on Gaussian predictive distributions. They
complement the existing ECE/Brier/AUROC calibration metrics by
measuring the *sharpness* of the uncertainty estimate, not just its
calibration.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import ArrayLike, NDArray


def interval_score(
    lower: ArrayLike,
    upper: ArrayLike,
    actual: ArrayLike,
    alpha: float = 0.1,
) -> float:
    """Winkler interval score averaged over all examples.

    For a ``(1-alpha)``-level prediction interval ``[lower, upper]``:

        IS = (upper - lower)
             + (2/alpha) * max(lower - actual, 0)
             + (2/alpha) * max(actual - upper, 0)

    Lower is better. A tight interval that covers the truth scores best.

    Parameters
    ----------
    lower, upper : array-like of float
        Lower and upper bounds of the prediction interval.
    actual : array-like of float
        Observed values.
    alpha : float
        Miscoverage level (e.g. 0.1 for a 90 % interval).
    """
    lo = np.asarray(lower, dtype=np.float64).ravel()
    hi = np.asarray(upper, dtype=np.float64).ravel()
    y = np.asarray(actual, dtype=np.float64).ravel()
    if not (lo.shape == hi.shape == y.shape):
        raise ValueError("lower, upper, actual must have the same shape")
    if lo.size == 0:
        raise ValueError("inputs must be non-empty")
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")

    width = hi - lo
    penalty_lo = (2.0 / alpha) * np.maximum(lo - y, 0.0)
    penalty_hi = (2.0 / alpha) * np.maximum(y - hi, 0.0)
    return float(np.mean(width + penalty_lo + penalty_hi))


def crps_gaussian(
    mean: ArrayLike,
    std: ArrayLike,
    actual: ArrayLike,
) -> float:
    """Continuous Ranked Probability Score for Gaussian predictions.

    Closed-form (Gneiting & Raftery 2007, eq. 21):

        CRPS = std * [ z * (2*Phi(z) - 1) + 2*phi(z) - 1/sqrt(pi) ]

    where ``z = (actual - mean) / std``, ``Phi`` is the standard normal
    CDF, and ``phi`` is the standard normal PDF.

    Lower is better. Returns the mean CRPS across all examples.
    """
    mu = np.asarray(mean, dtype=np.float64).ravel()
    sigma = np.asarray(std, dtype=np.float64).ravel()
    y = np.asarray(actual, dtype=np.float64).ravel()
    if not (mu.shape == sigma.shape == y.shape):
        raise ValueError("mean, std, actual must have the same shape")
    if mu.size == 0:
        raise ValueError("inputs must be non-empty")
    if np.any(sigma <= 0.0):
        raise ValueError("std must be strictly positive")

    z = (y - mu) / sigma
    phi_z = np.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    big_phi_z = 0.5 * (1.0 + _erf_approx(z / math.sqrt(2.0)))
    crps_per = sigma * (z * (2.0 * big_phi_z - 1.0) + 2.0 * phi_z - 1.0 / math.sqrt(math.pi))
    return float(np.mean(crps_per))


def _erf_approx(x: NDArray[np.float64]) -> NDArray[np.float64]:
    """Vectorized error function approximation (Abramowitz & Stegun 7.1.28).

    Max absolute error < 5e-4 over the real line. Good enough for CRPS
    where the score itself has ~1 % estimation noise from finite N.
    """
    sign = np.sign(x)
    t = 1.0 / (1.0 + 0.3275911 * np.abs(x))
    poly = t * (
        0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429)))
    )
    return np.asarray(sign * (1.0 - poly * np.exp(-x * x)), dtype=np.float64)


def crps_from_confidence(
    confs: ArrayLike,
    correct: ArrayLike,
) -> float:
    """CRPS proxy for LUB's classification-style confidence scores.

    Treats each ``(confidence, correct)`` pair as a Bernoulli forecast:
    the predicted probability of correctness is ``conf``, and the outcome
    is ``correct in {0, 1}``. The Bernoulli CRPS simplifies to:

        CRPS_bernoulli = conf^2 * (1 - correct) + (1 - conf)^2 * correct

    which is exactly the Brier score. This function is provided for API
    symmetry so callers can import from ``scoring_rules`` uniformly.
    """
    c = np.asarray(confs, dtype=np.float64).ravel()
    y = np.asarray(correct, dtype=np.float64).ravel()
    if c.shape != y.shape:
        raise ValueError("confs and correct must have the same shape")
    if c.size == 0:
        raise ValueError("inputs must be non-empty")
    return float(np.mean((c - y) ** 2))


def negative_log_likelihood(
    confs: ArrayLike,
    correct: ArrayLike,
    eps: float = 1e-12,
) -> float:
    """Binary classification NLL (log loss) for confidence forecasts.

    For each (conf, correct) pair, treats ``conf`` as the predicted
    probability that ``correct == 1``. Computes

        NLL = -mean(correct * log(conf) + (1 - correct) * log(1 - conf))

    Lower is better. ``0`` for a perfect, confident forecaster;
    unbounded above when the forecaster is confidently wrong.

    ``eps`` clips confidences to ``[eps, 1 - eps]`` to avoid ``log(0)``;
    NLL can still be unbounded above on truly-wrong high-confidence
    forecasts.

    Reference: standard in the calibration literature; see e.g.
    Guo et al. 2017 "On Calibration of Modern Neural Networks" Table 2.
    """
    c = np.asarray(confs, dtype=np.float64).ravel()
    y = np.asarray(correct, dtype=np.float64).ravel()
    if c.shape != y.shape:
        raise ValueError("confs and correct must have the same shape")
    if c.size == 0:
        raise ValueError("inputs must be non-empty")
    if np.any((c < 0.0) | (c > 1.0)):
        raise ValueError("confs must lie in [0, 1]")
    if not 0.0 < eps < 0.5:
        raise ValueError(f"eps must lie in (0, 0.5), got {eps}")

    c_clipped = np.clip(c, eps, 1.0 - eps)
    nll = -(y * np.log(c_clipped) + (1.0 - y) * np.log(1.0 - c_clipped))
    return float(np.mean(nll))


def pinball_loss(
    quantile_pred: ArrayLike,
    actual: ArrayLike,
    tau: float,
) -> float:
    """Pinball (check) loss for a predicted tau-quantile.

    For each (q, y) pair where ``q`` is the predicted ``tau``-quantile
    of the predictive distribution and ``y`` is the realized value:

        L_tau(q, y) = tau * max(y - q, 0) + (1 - tau) * max(q - y, 0)

    Averaged across all examples. Lower is better; ``0`` iff the
    predicted quantile equals the truth on every example.

    For a symmetric predictive interval ``[q_lo, q_hi]`` at level
    ``1 - alpha``, set ``tau = alpha / 2`` for ``q_lo`` and
    ``tau = 1 - alpha / 2`` for ``q_hi``; the sum ``pinball(q_lo) +
    pinball(q_hi)`` is proportional to :func:`interval_score`.

    Reference: Koenker & Bassett 1978, "Regression Quantiles,"
    Econometrica 46(1).
    """
    q = np.asarray(quantile_pred, dtype=np.float64).ravel()
    y = np.asarray(actual, dtype=np.float64).ravel()
    if q.shape != y.shape:
        raise ValueError("quantile_pred and actual must have the same shape")
    if q.size == 0:
        raise ValueError("inputs must be non-empty")
    if not 0.0 < tau < 1.0:
        raise ValueError(f"tau must be in (0, 1), got {tau}")

    err = y - q
    loss = np.where(err >= 0.0, tau * err, (tau - 1.0) * err)
    return float(np.mean(loss))


__all__ = [
    "crps_from_confidence",
    "crps_gaussian",
    "interval_score",
    "negative_log_likelihood",
    "pinball_loss",
]
