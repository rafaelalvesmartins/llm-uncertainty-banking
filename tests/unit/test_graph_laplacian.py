# Copyright 2026 Rafael Martins Alves — Apache-2.0

from __future__ import annotations

import pytest

from lub.uncertainty.graph_laplacian import GraphLaplacianEstimator, _jaccard
from lub.wrappers.dummy import DummyBackend


def test_jaccard_identical_strings() -> None:
    assert _jaccard("hello world", "hello world") == 1.0


def test_jaccard_disjoint_strings() -> None:
    assert _jaccard("hello", "world") == 0.0


def test_jaccard_partial_overlap() -> None:
    score = _jaccard("hello world foo", "hello world bar")
    assert 0.0 < score < 1.0
    assert score == pytest.approx(2.0 / 4.0)


def test_jaccard_empty_strings() -> None:
    assert _jaccard("", "") == 1.0


def test_score_returns_valid_result(backend: DummyBackend) -> None:
    est = GraphLaplacianEstimator(n_samples=5)
    result = est.score(backend, "What is Basel III?")
    assert result.answer
    assert 0.0 <= result.confidence <= 1.0


def test_raw_scores_contain_spectral_info(backend: DummyBackend) -> None:
    est = GraphLaplacianEstimator(n_samples=5)
    result = est.score(backend, "q")
    assert "n_samples" in result.raw_scores
    assert result.raw_scores["n_samples"] == 5.0


def test_samples_returned(backend: DummyBackend) -> None:
    est = GraphLaplacianEstimator(n_samples=4)
    result = est.score(backend, "q")
    assert result.samples is not None
    assert len(result.samples) == 4


def test_refusal_triggers_below_threshold(backend: DummyBackend) -> None:
    est = GraphLaplacianEstimator(n_samples=5, refusal_threshold=0.99)
    result = est.score(backend, "q")
    assert result.should_refuse is True


def test_deterministic_with_same_prompt(backend: DummyBackend) -> None:
    est = GraphLaplacianEstimator(n_samples=5)
    a = est.score(backend, "same prompt here")
    b = est.score(DummyBackend(model_id="dummy-0"), "same prompt here")
    assert a.confidence == pytest.approx(b.confidence)
