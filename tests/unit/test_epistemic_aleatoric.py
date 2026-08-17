# Copyright 2026 Rafael Martins Alves — Apache-2.0

from __future__ import annotations

import pytest

from lub.uncertainty.epistemic_aleatoric import EpistemicAleatoricEstimator
from lub.wrappers.dummy import DummyBackend


def test_returns_uncertainty_result(backend: DummyBackend) -> None:
    est = EpistemicAleatoricEstimator(n_samples=5)
    result = est.score(backend, "What is Basel III CET1?")
    assert result.answer
    assert 0.0 <= result.confidence <= 1.0


def test_raw_scores_contain_decomposition(backend: DummyBackend) -> None:
    est = EpistemicAleatoricEstimator(n_samples=5)
    result = est.score(backend, "q")
    for key in ("epistemic_uncertainty", "aleatoric_entropy", "total_entropy"):
        assert key in result.raw_scores, f"missing key {key}"
        assert isinstance(result.raw_scores[key], float)


def test_epistemic_and_aleatoric_are_nonnegative(backend: DummyBackend) -> None:
    est = EpistemicAleatoricEstimator(n_samples=10)
    result = est.score(backend, "q")
    assert result.raw_scores["epistemic_uncertainty"] >= 0.0
    assert result.raw_scores["aleatoric_entropy"] >= 0.0
    assert result.raw_scores["total_entropy"] >= 0.0


def test_refusal_below_threshold(backend: DummyBackend) -> None:
    est = EpistemicAleatoricEstimator(n_samples=5, refusal_threshold=0.99)
    result = est.score(backend, "q")
    assert result.should_refuse is True


def test_samples_returned(backend: DummyBackend) -> None:
    est = EpistemicAleatoricEstimator(n_samples=4)
    result = est.score(backend, "q")
    assert result.samples is not None
    assert len(result.samples) == 4


def test_deterministic_with_same_prompt(backend: DummyBackend) -> None:
    est = EpistemicAleatoricEstimator(n_samples=5)
    a = est.score(backend, "same prompt")
    b = est.score(DummyBackend(model_id="dummy-0"), "same prompt")
    assert a.confidence == pytest.approx(b.confidence)
