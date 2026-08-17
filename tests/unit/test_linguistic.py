# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for the linguistic calibration score metric."""

from __future__ import annotations

import pytest

from lub.calibration.linguistic import (
    extract_implied_probability,
    linguistic_calibration_report,
    linguistic_calibration_score,
)


class TestExtractImpliedProbability:
    def test_high_confidence_hedge(self) -> None:
        prob, hedge = extract_implied_probability("I'm confident that the answer is 42.")
        assert prob == pytest.approx(0.90)
        assert hedge is not None

    def test_medium_confidence_hedge(self) -> None:
        prob, hedge = extract_implied_probability("The answer is probably 42.")
        assert prob == pytest.approx(0.75)
        assert hedge is not None

    def test_low_confidence_hedge(self) -> None:
        prob, hedge = extract_implied_probability("I'm not sure, but maybe 42?")
        # "I'm not sure" matches first at 0.35
        assert prob <= 0.50
        assert hedge is not None

    def test_no_hedge_returns_default(self) -> None:
        prob, hedge = extract_implied_probability("The answer is 42.")
        assert prob == pytest.approx(0.85)
        assert hedge is None

    def test_certainly_matches(self) -> None:
        prob, _ = extract_implied_probability("The CET1 ratio is certainly above 8%.")
        assert prob == pytest.approx(0.95)

    def test_unlikely_matches(self) -> None:
        prob, _ = extract_implied_probability("It is unlikely that this exceeds the threshold.")
        assert prob == pytest.approx(0.20)

    def test_very_unlikely_matches(self) -> None:
        prob, _ = extract_implied_probability("This is very unlikely to happen.")
        assert prob == pytest.approx(0.10)

    def test_possibly_matches(self) -> None:
        prob, _ = extract_implied_probability("It's possible that the rate changed.")
        assert prob == pytest.approx(0.50)

    def test_case_insensitive(self) -> None:
        prob, hedge = extract_implied_probability("PROBABLY the answer is 42.")
        assert prob == pytest.approx(0.75)
        assert hedge is not None


class TestLinguisticCalibrationScore:
    def test_perfectly_calibrated_hedging(self) -> None:
        # "probably" (0.75) with 75% correct → perfect calibration
        texts = ["probably yes"] * 100
        correct = [1] * 75 + [0] * 25
        score = linguistic_calibration_score(texts, correct)
        # Brier score: mean((0.75 - y)^2)
        # 75 correct: (0.75-1)^2 = 0.0625, 25 wrong: (0.75-0)^2 = 0.5625
        expected = (75 * 0.0625 + 25 * 0.5625) / 100
        assert score == pytest.approx(expected, abs=0.01)

    def test_overconfident_hedging(self) -> None:
        # "certainly" (0.95) but only 50% correct → bad calibration
        texts = ["certainly yes"] * 100
        correct = [1] * 50 + [0] * 50
        score = linguistic_calibration_score(texts, correct)
        assert score > 0.3  # Should be high (badly calibrated)

    def test_well_calibrated_is_lower(self) -> None:
        texts_good = ["probably yes"] * 100
        correct_good = [1] * 75 + [0] * 25
        texts_bad = ["certainly yes"] * 100
        correct_bad = [1] * 50 + [0] * 50
        score_good = linguistic_calibration_score(texts_good, correct_good)
        score_bad = linguistic_calibration_score(texts_bad, correct_bad)
        assert score_good < score_bad

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            linguistic_calibration_score([], [])

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            linguistic_calibration_score(["a", "b"], [1])

    def test_score_in_valid_range(self) -> None:
        texts = ["maybe yes", "certainly no", "probably yes"]
        correct = [1, 0, 1]
        score = linguistic_calibration_score(texts, correct)
        assert 0.0 <= score <= 1.0


class TestLinguisticCalibrationReport:
    def test_report_has_expected_fields(self) -> None:
        texts = ["probably yes", "maybe no", "certainly yes"]
        correct = [1, 0, 1]
        report = linguistic_calibration_report(texts, correct)
        assert "linguistic_calibration_score" in report
        assert "n" in report
        assert "n_hedged" in report
        assert "n_bare_assertion" in report
        assert "breakdown" in report

    def test_report_n_matches_input(self) -> None:
        texts = ["a", "b", "c"]
        correct = [1, 0, 1]
        report = linguistic_calibration_report(texts, correct)
        assert report["n"] == 3

    def test_report_breakdown_has_categories(self) -> None:
        texts = ["probably yes", "certainly no"]
        correct = [1, 0]
        report = linguistic_calibration_report(texts, correct)
        breakdown = report["breakdown"]
        assert isinstance(breakdown, list)
        assert len(breakdown) >= 1
        for cat in breakdown:
            assert "implied_probability" in cat
            assert "count" in cat
            assert "mean_accuracy" in cat
            assert "gap" in cat

    def test_report_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            linguistic_calibration_report([], [])

    def test_hedged_count(self) -> None:
        texts = ["probably yes", "The answer is 42.", "certainly no"]
        correct = [1, 1, 0]
        report = linguistic_calibration_report(texts, correct)
        assert report["n_hedged"] == 2
        assert report["n_bare_assertion"] == 1
