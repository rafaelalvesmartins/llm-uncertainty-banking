# Copyright 2026 Rafael Martins Alves — Apache-2.0

from __future__ import annotations

import pytest

from lub.uncertainty.mahalanobis import MahalanobisEstimator
from lub.wrappers.dummy import DummyBackend


def test_mahalanobis_returns_valid_confidence(dummy_backend: DummyBackend) -> None:
    est = MahalanobisEstimator(n_samples=3)
    result = est.score(dummy_backend, "What is CET1?")
    assert 0.0 <= result.confidence <= 1.0
    assert result.answer
    assert "mean_mahalanobis" in result.raw_scores
    assert "max_mahalanobis" in result.raw_scores


def test_mahalanobis_name() -> None:
    assert MahalanobisEstimator.REGISTRY_KEY == "mahalanobis"


def test_mahalanobis_rejects_too_few_samples() -> None:
    with pytest.raises(ValueError):
        MahalanobisEstimator(n_samples=1)


def test_mahalanobis_rejects_bad_threshold() -> None:
    with pytest.raises(ValueError):
        MahalanobisEstimator(refusal_threshold=-0.1)


def test_mahalanobis_samples_count(dummy_backend: DummyBackend) -> None:
    est = MahalanobisEstimator(n_samples=4)
    result = est.score(dummy_backend, "q")
    assert len(result.samples) == 4
    assert result.raw_scores["n_samples"] == 4.0
