"""Shared numerical primitives for uncertainty estimators.

This module consolidates a handful of small numeric routines that were
previously duplicated across estimators (``entropy = -sum(p log p)``,
numerically stable softmax, mean-logprob → confidence). Centralising them
keeps the math consistent (same handling of zero-probability terms, same
log base, same NaN/empty-input semantics) and gives us one place to test
the edge cases.

These helpers are intentionally pure and dependency-free (stdlib ``math``
only). They are private to ``lub.uncertainty`` — estimator modules may
import them directly, but they are not part of the public API.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

__all__ = [
    "entropy_from_probs",
    "stable_softmax",
    "mean_logprob_confidence",
]


def entropy_from_probs(
    probs: Iterable[float],
    *,
    base: float | None = None,
) -> float:
    """Shannon entropy ``-sum(p * log(p))`` over an iterable of probabilities.

    Non-positive probabilities (``p <= 0``) are skipped — both because
    ``log(0)`` is undefined and because, by the usual ``0 * log(0) := 0``
    convention, those terms contribute nothing. This matches the inline
    implementations that existed in :mod:`epistemic_aleatoric`,
    :mod:`semantic_entropy` and :mod:`monte_carlo_dropout` before this
    helper was extracted.

    Args:
        probs: Iterable of probabilities. They do not need to sum to 1
            (callers may pass a slice or a normalized weight vector).
        base: Logarithm base. ``None`` (default) means natural log
            (``math.log``). Pass ``2`` for bits, ``10`` for bans.

    Returns:
        The Shannon entropy as a non-negative float. Returns ``0.0`` for
        an empty iterable or one in which every value is non-positive.
    """
    if base is None:
        def log(x: float) -> float:
            """Log (natural)."""
            return math.log(x)
    else:
        log_base = math.log(base)

        def log(x: float) -> float:
            """Log (base-rescaled)."""
            return math.log(x) / log_base

    total = 0.0
    for p in probs:
        if p > 0.0:
            total -= p * log(p)
    return total


def stable_softmax(logits: Sequence[float]) -> list[float]:
    """Numerically stable softmax over a sequence of logits.

    Uses the standard ``exp(x - max(x))`` trick to avoid overflow when
    logits have large magnitude. Equivalent to the inline computations
    in :mod:`p_true` (binary case) and :mod:`semantic_entropy`
    (variable-arity case).

    Args:
        logits: A non-empty sequence of real-valued logits.

    Returns:
        A list of probabilities of the same length as ``logits``,
        summing to 1.0 (up to floating-point precision).

    Raises:
        ValueError: If ``logits`` is empty.
    """
    if not logits:
        raise ValueError("stable_softmax requires at least one logit")
    m = max(logits)
    unnorm = [math.exp(lw - m) for lw in logits]
    total = sum(unnorm)
    return [u / total for u in unnorm]


def mean_logprob_confidence(
    logprobs: Sequence[float],
) -> tuple[float, float]:
    """Reduce a list of token logprobs to ``(mean_logprob, confidence)``.

    Convention used across :mod:`token_logprob` and :mod:`perplexity`:
    confidence is ``exp(mean_logprob)`` clipped to ``[0, 1]``. For empty
    input we return ``(nan, 0.0)`` so callers can still record the missing
    measurement in their diagnostics dict.

    Args:
        logprobs: Per-token log-probabilities. May be empty.

    Returns:
        Tuple ``(mean_logprob, confidence)``.

        * ``mean_logprob`` — arithmetic mean of the input, or ``nan`` for
          empty input.
        * ``confidence`` — ``exp(mean_logprob)`` clipped to ``[0.0, 1.0]``,
          or ``0.0`` for empty input.
    """
    if not logprobs:
        return float("nan"), 0.0
    mean_lp = sum(logprobs) / len(logprobs)
    conf = math.exp(mean_lp)
    if conf < 0.0:
        conf = 0.0
    elif conf > 1.0:
        conf = 1.0
    return mean_lp, conf
