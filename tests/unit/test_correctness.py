# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for lub.benchmarks.correctness."""

from __future__ import annotations

import pytest

from lub.benchmarks.correctness import (
    CorrectnessFn,
    choice_match,
    exact_match,
    fuzzy_match,
)


class TestExactMatch:
    """Tests for exact_match scorer."""

    def test_identical_strings_match(self) -> None:
        assert exact_match("hello", "hello") is True

    def test_case_insensitive_match(self) -> None:
        assert exact_match("Hello", "hello") is True
        assert exact_match("YES", "yes") is True

    def test_whitespace_normalized(self) -> None:
        assert exact_match("  hello  world  ", "hello world") is True

    def test_punctuation_stripped(self) -> None:
        assert exact_match("hello!", "hello") is True
        assert exact_match("yes?", "yes") is True

    def test_decimal_point_preserved_in_numbers(self) -> None:
        assert exact_match("4.5", "4.5") is True

    def test_numeric_equality_with_comma_separator(self) -> None:
        assert exact_match("1,234.50", "1234.5") is True

    def test_numeric_equality_with_percent(self) -> None:
        assert exact_match("4.5%", "4.5") is True
        assert exact_match("1234.50%", "1234.5") is True

    def test_numeric_inequality(self) -> None:
        assert exact_match("4.5", "5.5") is False

    def test_non_numeric_mismatch(self) -> None:
        assert exact_match("positive", "negative") is False

    def test_empty_strings_match(self) -> None:
        assert exact_match("", "") is True

    def test_numeric_within_tolerance(self) -> None:
        assert exact_match("1.0000000001", "1.0") is True

    def test_negative_number_match(self) -> None:
        assert exact_match("-4.5", "-4.5") is True


class TestFuzzyMatch:
    """Tests for fuzzy_match scorer."""

    def test_exact_string_match(self) -> None:
        assert fuzzy_match("hello", "hello") is True

    def test_gold_substring_in_pred(self) -> None:
        assert fuzzy_match(
            "The minimum CET1 ratio is approximately 4.5 percent",
            "4.5 percent",
        ) is True

    def test_short_gold_not_substring_match(self) -> None:
        # gold_norm length < 3 should not substring match
        assert fuzzy_match("the number is 1234", "12") is False

    def test_numeric_match_in_verbose_pred(self) -> None:
        assert fuzzy_match("The answer is 4.5% under Basel III.", "4.5%") is True

    def test_numeric_equality_pure(self) -> None:
        assert fuzzy_match("1,234.50", "1234.5") is True

    def test_no_match(self) -> None:
        assert fuzzy_match("completely unrelated text", "specific gold answer") is False

    def test_numeric_token_in_pred_matches_gold_number(self) -> None:
        assert fuzzy_match("The capital ratio is 1,234.5 basis points", "1234.5") is True

    def test_case_insensitive_substring(self) -> None:
        assert fuzzy_match("The answer is POSITIVE today", "positive") is True

    def test_numeric_with_punctuation_in_token(self) -> None:
        assert fuzzy_match("the value is 4.5, according to the report", "4.5") is True


class TestChoiceMatch:
    """Tests for choice_match factory."""

    @pytest.fixture
    def sentiment_scorer(self) -> CorrectnessFn:
        return choice_match(choices=("positive", "negative", "neutral"))

    @pytest.fixture
    def sentiment_with_synonyms(self) -> CorrectnessFn:
        return choice_match(
            choices=("rise", "fall"),
            synonyms={
                "rise": ("yes", "positive", "up"),
                "fall": ("no", "negative", "down"),
            },
        )

    def test_direct_choice_match(self, sentiment_scorer: CorrectnessFn) -> None:
        assert sentiment_scorer("positive", "positive") is True

    def test_choice_substring_in_pred(self, sentiment_scorer: CorrectnessFn) -> None:
        assert sentiment_scorer("The sentiment is positive overall", "positive") is True

    def test_choice_wrong_label(self, sentiment_scorer: CorrectnessFn) -> None:
        assert sentiment_scorer("positive", "negative") is False

    def test_no_choice_found(self, sentiment_scorer: CorrectnessFn) -> None:
        assert sentiment_scorer("I don't know", "positive") is False

    def test_case_insensitive_matching(self, sentiment_scorer: CorrectnessFn) -> None:
        assert sentiment_scorer("POSITIVE", "positive") is True
        assert sentiment_scorer("positive", "POSITIVE") is True

    def test_synonym_match(self, sentiment_with_synonyms: CorrectnessFn) -> None:
        assert sentiment_with_synonyms("yes", "rise") is True
        assert sentiment_with_synonyms("the stock will go up", "rise") is True

    def test_synonym_wrong_label(self, sentiment_with_synonyms: CorrectnessFn) -> None:
        assert sentiment_with_synonyms("yes", "fall") is False

    def test_canonical_takes_precedence_over_synonym(
        self, sentiment_with_synonyms: CorrectnessFn
    ) -> None:
        # "rise" is a canonical choice, so it should match directly
        assert sentiment_with_synonyms("rise", "rise") is True

    def test_default_fallback(self) -> None:
        scorer = choice_match(
            choices=("yes", "no"),
            default="no",
        )
        # Prediction matches neither choice nor synonym, default to "no"
        assert scorer("I cannot say", "no") is True
        assert scorer("I cannot say", "yes") is False

    def test_no_default_no_match(self) -> None:
        scorer = choice_match(choices=("yes", "no"))
        assert scorer("maybe", "yes") is False
        assert scorer("maybe", "no") is False

    def test_first_matching_choice_wins(self) -> None:
        scorer = choice_match(choices=("good", "bad"))
        # Both substrings present; first in choices order wins
        assert scorer("good and bad", "good") is True
        assert scorer("good and bad", "bad") is False

    def test_empty_synonym_phrases_ignored(self) -> None:
        scorer = choice_match(
            choices=("yes", "no"),
            synonyms={"yes": ("", "  ", "affirmative")},
        )
        assert scorer("affirmative", "yes") is True

    def test_returns_callable(self) -> None:
        scorer = choice_match(choices=("a", "b"))
        assert callable(scorer)


class TestCorrectnessFnType:
    """Tests for the CorrectnessFn type alias."""

    def test_exact_match_satisfies_signature(self) -> None:
        fn: CorrectnessFn = exact_match
        assert fn("a", "a") is True

    def test_fuzzy_match_satisfies_signature(self) -> None:
        fn: CorrectnessFn = fuzzy_match
        assert fn("a", "a") is True

    def test_choice_match_returns_correctness_fn(self) -> None:
        fn: CorrectnessFn = choice_match(choices=("x", "y"))
        assert fn("x", "x") is True
