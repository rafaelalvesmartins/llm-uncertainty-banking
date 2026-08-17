# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for the SentenceSAR estimator."""

from __future__ import annotations

import pytest

from lub.uncertainty.sentence_sar import SentenceSAREstimator
from lub.wrappers.dummy import DummyBackend


def test_sentence_sar_returns_valid_confidence(dummy_backend: DummyBackend) -> None:
    est = SentenceSAREstimator(n_samples=3)
    result = est.score(dummy_backend, "What is CET1?")
    assert 0.0 <= result.confidence <= 1.0
    assert result.answer
    assert "sentence_sar" in result.raw_scores
    assert "mean_token_sar" in result.raw_scores
    assert "n_valid" in result.raw_scores
    assert "n_samples" in result.raw_scores


def test_sentence_sar_registry_key() -> None:
    assert SentenceSAREstimator.REGISTRY_KEY == "sentence_sar"


def test_sentence_sar_rejects_bad_threshold() -> None:
    with pytest.raises(ValueError):
        SentenceSAREstimator(refusal_threshold=1.5)


def test_sentence_sar_rejects_n_samples_below_2() -> None:
    with pytest.raises(ValueError):
        SentenceSAREstimator(n_samples=1)


def test_sentence_sar_rejects_bad_temperature() -> None:
    with pytest.raises(ValueError):
        SentenceSAREstimator(temperature=0.0)


def test_sentence_sar_samples_returned(dummy_backend: DummyBackend) -> None:
    est = SentenceSAREstimator(n_samples=4)
    result = est.score(dummy_backend, "test prompt")
    assert result.samples is not None
    assert len(result.samples) >= 2


def test_sentence_sar_should_refuse_when_below_threshold(
    dummy_backend: DummyBackend,
) -> None:
    est = SentenceSAREstimator(n_samples=3, refusal_threshold=0.99)
    result = est.score(dummy_backend, "q")
    assert result.should_refuse or result.confidence >= 0.99


def test_sentence_sar_deterministic_across_calls(
    dummy_backend: DummyBackend,
) -> None:
    est = SentenceSAREstimator(n_samples=3)
    r1 = est.score(dummy_backend, "same prompt")
    r2 = est.score(dummy_backend, "same prompt")
    assert r1.confidence == pytest.approx(r2.confidence)
    assert r1.answer == r2.answer


def test_sentence_sar_raw_scores_range(dummy_backend: DummyBackend) -> None:
    est = SentenceSAREstimator(n_samples=3)
    result = est.score(dummy_backend, "test")
    assert result.raw_scores["n_valid"] >= 1.0
    assert result.raw_scores["n_samples"] >= 2.0
    assert result.raw_scores["min_token_sar"] <= result.raw_scores["max_token_sar"]
