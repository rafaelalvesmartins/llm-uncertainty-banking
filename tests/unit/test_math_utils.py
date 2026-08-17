# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for lub.uncertainty._math_utils.

These helpers consolidate entropy / softmax / mean-logprob computations
that several estimators previously duplicated. The tests pin down the
contract -- in particular the edge cases (empty input, all-zero input,
extreme magnitudes) -- so future refactoring of estimators stays
bit-for-bit consistent with the inline implementations they replaced.
"""

from __future__ import annotations

import math

import pytest

from lub.uncertainty._math_utils import (
    entropy_from_probs,
    mean_logprob_confidence,
    stable_softmax,
)

# ---------------------------------------------------------------------------
# entropy_from_probs
# ---------------------------------------------------------------------------

def test_entropy_empty_iterable_returns_zero() -> None:
    assert entropy_from_probs([]) == 0.0


def test_entropy_singleton_one_returns_zero() -> None:
    """log(1) = 0, so a degenerate distribution has zero entropy."""
    assert entropy_from_probs([1.0]) == 0.0


def test_entropy_uniform_two_outcomes_equals_log2() -> None:
    h = entropy_from_probs([0.5, 0.5])
    assert math.isclose(h, math.log(2), abs_tol=1e-15)


def test_entropy_uniform_in_bits() -> None:
    """Same uniform distribution is exactly 1 bit when base=2."""
    h = entropy_from_probs([0.5, 0.5], base=2)
    assert math.isclose(h, 1.0, abs_tol=1e-15)


def test_entropy_skips_zero_probabilities() -> None:
    """Skipping ``0 * log(0)`` follows the standard convention."""
    h_with_zero = entropy_from_probs([0.0, 0.5, 0.5])
    h_without_zero = entropy_from_probs([0.5, 0.5])
    assert math.isclose(h_with_zero, h_without_zero, abs_tol=1e-15)


def test_entropy_skips_negative_probabilities() -> None:
    """Negative inputs are treated as the same skip case (defensive)."""
    h = entropy_from_probs([-0.1, 0.5, 0.5])
    assert math.isclose(h, math.log(2), abs_tol=1e-15)


def test_entropy_unnormalised_probs_are_ok() -> None:
    """The function does not require sum-to-1 -- callers may pass a
    weight slice. Check it computes -sum(p * log(p)) literally."""
    probs = [0.2, 0.3, 0.4]
    expected = -sum(p * math.log(p) for p in probs)
    assert math.isclose(entropy_from_probs(probs), expected, abs_tol=1e-15)


# ---------------------------------------------------------------------------
# stable_softmax
# ---------------------------------------------------------------------------

def test_softmax_uniform_logits_are_uniform_probs() -> None:
    sm = stable_softmax([0.0, 0.0, 0.0])
    assert all(math.isclose(p, 1 / 3, abs_tol=1e-15) for p in sm)


def test_softmax_sums_to_one() -> None:
    sm = stable_softmax([-2.5, -1.0, -0.3, -5.7])
    assert math.isclose(sum(sm), 1.0, abs_tol=1e-15)


def test_softmax_handles_extreme_logits_without_overflow() -> None:
    """A naive ``exp(x)`` would overflow at 1000; the stable trick must work."""
    sm = stable_softmax([1000.0, 1000.0, 1000.0])
    assert all(math.isclose(p, 1 / 3, abs_tol=1e-15) for p in sm)


def test_softmax_empty_raises() -> None:
    with pytest.raises(ValueError):
        stable_softmax([])


def test_softmax_binary_matches_inline_pattern() -> None:
    """Replicate the exact computation that lived in p_true._whitebox_ptrue."""
    lp_true, lp_false = -3.2, -4.1
    m = max(lp_true, lp_false)
    expected_p_true = math.exp(lp_true - m) / (
        math.exp(lp_true - m) + math.exp(lp_false - m)
    )
    [p_true_new, _] = stable_softmax([lp_true, lp_false])
    assert math.isclose(p_true_new, expected_p_true, abs_tol=1e-15)


# ---------------------------------------------------------------------------
# mean_logprob_confidence
# ---------------------------------------------------------------------------

def test_mlc_empty_returns_nan_and_zero() -> None:
    ml, c = mean_logprob_confidence([])
    assert math.isnan(ml)
    assert c == 0.0


def test_mlc_single_value() -> None:
    ml, c = mean_logprob_confidence([math.log(0.5)])
    assert math.isclose(ml, math.log(0.5), abs_tol=1e-15)
    assert math.isclose(c, 0.5, abs_tol=1e-15)


def test_mlc_clips_above_one() -> None:
    """``exp(mean_logprob)`` of a positive logprob would exceed 1 --
    must be clamped because confidence lives in [0, 1]."""
    ml, c = mean_logprob_confidence([math.log(2.0)])
    assert ml > 0.0
    assert c == 1.0


def test_mlc_clips_below_zero_is_unreachable_but_safe() -> None:
    """``exp`` is always non-negative for finite input, but the clamp
    must still be there in case of weird numpy NaN or -inf."""
    ml, c = mean_logprob_confidence([float("-inf")])
    # -inf mean -> exp(-inf) = 0
    assert c == 0.0


def test_mlc_arithmetic_mean_of_three() -> None:
    lps = [-0.1, -0.2, -0.05]
    expected_ml = sum(lps) / len(lps)
    expected_c = math.exp(expected_ml)
    ml, c = mean_logprob_confidence(lps)
    assert math.isclose(ml, expected_ml, abs_tol=1e-15)
    assert math.isclose(c, expected_c, abs_tol=1e-15)
