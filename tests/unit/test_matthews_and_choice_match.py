# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for Matthews correlation (L3) and PIXIU-style choice matching (L4)."""

from __future__ import annotations

import numpy as np
import pytest

from lub.benchmarks.runner import choice_match
from lub.calibration.metrics import matthews_correlation

# ---- Matthews correlation -------------------------------------------------


def test_mcc_perfect_agreement_is_one() -> None:
    pred = np.array([1, 0, 1, 0, 1])
    correct = np.array([1, 0, 1, 0, 1])
    assert matthews_correlation(pred, correct) == pytest.approx(1.0)


def test_mcc_perfect_disagreement_is_negative_one() -> None:
    pred = np.array([0, 1, 0, 1])
    correct = np.array([1, 0, 1, 0])
    assert matthews_correlation(pred, correct) == pytest.approx(-1.0)


def test_mcc_random_is_near_zero() -> None:
    rng = np.random.default_rng(0)
    pred = rng.integers(0, 2, size=1000)
    correct = rng.integers(0, 2, size=1000)
    assert abs(matthews_correlation(pred, correct)) < 0.1


def test_mcc_degenerate_all_positive_returns_zero() -> None:
    assert matthews_correlation([1, 1, 1], [1, 1, 1]) == 0.0
    assert matthews_correlation([1, 1, 1], [0, 0, 0]) == 0.0


def test_mcc_accepts_boolean_and_float_inputs() -> None:
    mcc_bool = matthews_correlation([True, False, True], [True, False, True])
    mcc_float = matthews_correlation([1.0, 0.0, 1.0], [1.0, 0.0, 1.0])
    assert mcc_bool == pytest.approx(mcc_float)


def test_mcc_imbalanced_class_preferred_over_accuracy() -> None:
    # Dummy classifier: always predicts 0 on 99% zeros / 1% ones.
    # Accuracy ~ 99 %, MCC correctly flags it as useless (0).
    pred = np.zeros(100)
    correct = np.concatenate([np.zeros(99), np.ones(1)])
    assert matthews_correlation(pred, correct) == 0.0


def test_mcc_shape_mismatch_rejected() -> None:
    with pytest.raises(ValueError):
        matthews_correlation([1, 0, 1], [1])


def test_mcc_empty_rejected() -> None:
    with pytest.raises(ValueError):
        matthews_correlation([], [])


# ---- PIXIU-style choice_match ---------------------------------------------


def test_choice_match_direct_substring_hit() -> None:
    match = choice_match(choices=("positive", "negative", "neutral"))
    assert match("The sentiment is positive.", "positive") is True
    assert match("The sentiment is negative.", "positive") is False


def test_choice_match_is_case_insensitive() -> None:
    match = choice_match(choices=("positive", "negative"))
    assert match("POSITIVE", "positive") is True
    assert match("Positive", "positive") is True


def test_choice_match_synonym_fallback() -> None:
    match = choice_match(
        choices=("rise", "fall"),
        synonyms={"rise": ("yes", "up"), "fall": ("no", "down", "neutral")},
    )
    # Model emits "yes" — should be recognized as the gold "rise".
    assert match("yes", "rise") is True
    # Model emits "neutral" — synonym for fall.
    assert match("neutral", "fall") is True


def test_choice_match_default_fallback() -> None:
    match = choice_match(choices=("rise", "fall"), default="fall")
    # Model emits something unrelated — default "fall" wins.
    assert match("I don't know", "fall") is True
    assert match("I don't know", "rise") is False


def test_choice_match_no_hit_and_no_default_is_incorrect() -> None:
    match = choice_match(choices=("positive", "negative"))
    # No direct hit, no synonym, no default — must be False on any gold.
    assert match("potato", "positive") is False
    assert match("potato", "negative") is False


def test_choice_match_direct_hit_beats_synonym() -> None:
    # If the prediction contains the canonical choice itself, we should
    # not fall through to the synonym table of a different canonical.
    match = choice_match(
        choices=("rise", "fall"),
        synonyms={"fall": ("rise",)},  # intentionally pathological
    )
    # "rise" appears in the prediction, matches choice "rise" directly
    # (Step 1), so gold="rise" is correct, gold="fall" is not — despite
    # the pathological synonym table.
    assert match("price will rise", "rise") is True
    assert match("price will rise", "fall") is False
