# Copyright 2026 Rafael Martins Alves — Apache-2.0

from __future__ import annotations

import pytest

from lub.uncertainty.ensemble import EnsembleEstimator
from lub.uncertainty.perplexity import PerplexityEstimator
from lub.uncertainty.token_logprob import TokenLogprobEstimator
from lub.uncertainty.verbalized import VerbalizedOneShot
from lub.wrappers.dummy import DummyBackend


def test_ensemble_returns_valid_confidence(dummy_backend: DummyBackend) -> None:
    est = EnsembleEstimator(
        estimators=[TokenLogprobEstimator(), PerplexityEstimator()],
    )
    result = est.score(dummy_backend, "What is CET1?")
    assert 0.0 <= result.confidence <= 1.0
    assert result.answer
    assert "ensemble_confidence" in result.raw_scores
    assert "token_logprob_confidence" in result.raw_scores
    assert "perplexity_confidence" in result.raw_scores


def test_ensemble_name() -> None:
    est = EnsembleEstimator(
        estimators=[TokenLogprobEstimator(), PerplexityEstimator()],
    )
    assert est.REGISTRY_KEY == "ensemble"


def test_ensemble_rejects_single_estimator() -> None:
    with pytest.raises(ValueError):
        EnsembleEstimator(estimators=[TokenLogprobEstimator()])


def test_ensemble_rejects_mismatched_weights() -> None:
    with pytest.raises(ValueError):
        EnsembleEstimator(
            estimators=[TokenLogprobEstimator(), PerplexityEstimator()],
            weights=[1.0],
        )


def test_ensemble_custom_weights(dummy_backend: DummyBackend) -> None:
    est = EnsembleEstimator(
        estimators=[TokenLogprobEstimator(), PerplexityEstimator()],
        weights=[0.8, 0.2],
    )
    result = est.score(dummy_backend, "q")
    assert 0.0 <= result.confidence <= 1.0
    assert result.raw_scores["token_logprob_weight"] == pytest.approx(0.8)
    assert result.raw_scores["perplexity_weight"] == pytest.approx(0.2)


def test_ensemble_three_estimators(dummy_backend: DummyBackend) -> None:
    est = EnsembleEstimator(
        estimators=[
            TokenLogprobEstimator(),
            PerplexityEstimator(),
            VerbalizedOneShot(),
        ],
    )
    result = est.score(dummy_backend, "q")
    assert result.raw_scores["n_estimators"] == 3.0
    assert 0.0 <= result.confidence <= 1.0
