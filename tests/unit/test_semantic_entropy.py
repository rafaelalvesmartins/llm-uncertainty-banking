# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import pytest

from lub.types import UncertaintyResult
from lub.uncertainty.semantic_entropy import SemanticEntropyEstimator
from lub.wrappers.dummy import DummyBackend


def test_returns_valid_uncertainty_result(dummy_backend: DummyBackend) -> None:
    est = SemanticEntropyEstimator(n_samples=5, temperature=1.0, nli_model="nonexistent/model")
    result = est.score(dummy_backend, "What is the capital of France?")
    assert isinstance(result, UncertaintyResult)
    assert 0.0 <= result.confidence <= 1.0
    assert "entropy" in result.raw_scores
    assert "n_clusters" in result.raw_scores
    assert result.samples is not None
    assert len(result.samples) == 5


def test_fallback_clustering_when_nli_unavailable(dummy_backend: DummyBackend) -> None:
    est = SemanticEntropyEstimator(n_samples=3, nli_model="definitely/not/real")
    result = est.score(dummy_backend, "prompt")
    assert result.raw_scores["n_clusters"] >= 1.0


def test_refusal_threshold_is_honored(dummy_backend: DummyBackend) -> None:
    # DummyBackend samples are distinct -> entropy maxes, confidence ~= 0.
    strict = SemanticEntropyEstimator(
        n_samples=3, nli_model="nonexistent", refusal_threshold=0.5
    )
    r_strict = strict.score(dummy_backend, "q")
    assert r_strict.should_refuse is True

    permissive = SemanticEntropyEstimator(
        n_samples=3, nli_model="nonexistent", refusal_threshold=0.0
    )
    r_permissive = permissive.score(dummy_backend, "q")
    assert r_permissive.should_refuse is False


def test_refusal_threshold_validation() -> None:
    with pytest.raises(ValueError):
        SemanticEntropyEstimator(refusal_threshold=2.0)


def test_load_nli_cache_hit() -> None:
    """Second call to _load_nli returns cached value."""
    est = SemanticEntropyEstimator()
    est._nli_loaded = True
    est._nli = "sentinel"
    assert est._load_nli() == "sentinel"


def test_bidirectional_equivalent_exact_match_no_nli() -> None:
    est = SemanticEntropyEstimator()
    est._nli_loaded = True
    est._nli = None
    assert est._bidirectional_equivalent(None, "hello", "hello")
    assert est._bidirectional_equivalent(None, "  hello  ", "hello")


def test_bidirectional_equivalent_case_fallback_no_nli() -> None:
    est = SemanticEntropyEstimator()
    est._nli_loaded = True
    est._nli = None
    assert est._bidirectional_equivalent(None, "Hello", "hello")
    assert not est._bidirectional_equivalent(None, "Hello", "world")


def test_length_normalized_loglik_empty_logprobs() -> None:
    from lub.types import Generation

    gen = Generation(text="test", logprobs=None)
    assert SemanticEntropyEstimator._length_normalized_loglik(gen) == 0.0


def test_length_normalized_loglik_with_values() -> None:
    from lub.types import Generation

    gen = Generation(text="test", logprobs=[-1.0, -2.0, -3.0])
    assert SemanticEntropyEstimator._length_normalized_loglik(gen) == pytest.approx(-2.0)


def test_cluster_merges_identical_texts() -> None:
    est = SemanticEntropyEstimator()
    est._nli_loaded = True
    est._nli = None
    clusters = est._cluster(["hello", "hello", "world"])
    assert len(clusters) == 2
    assert sorted(len(c) for c in clusters) == [1, 2]


def test_entails_with_mock_nli() -> None:
    """Test _entails with a mock NLI that returns array-like scores."""

    class MockNLI:
        def predict(self, pairs: list[tuple[str, str]]) -> list[list[float]]:
            return [[0.1, 0.2, 0.9]]  # [contradiction, neutral, entailment]

    est = SemanticEntropyEstimator(entailment_threshold=0.5)
    assert est._entails(MockNLI(), "a", "b") is True


def test_entails_below_threshold() -> None:
    class MockNLI:
        def predict(self, pairs: list[tuple[str, str]]) -> list[list[float]]:
            return [[0.8, 0.1, 0.1]]

    est = SemanticEntropyEstimator(entailment_threshold=0.5)
    assert est._entails(MockNLI(), "a", "b") is False


def test_entails_scalar_score() -> None:
    """Handle backends that return scalar instead of array."""

    class MockNLI:
        def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
            return [0.7]

    est = SemanticEntropyEstimator(entailment_threshold=0.5)
    assert est._entails(MockNLI(), "a", "b") is True


def test_bidirectional_equivalent_with_nli() -> None:
    class MockNLI:
        def predict(self, pairs: list[tuple[str, str]]) -> list[list[float]]:
            return [[0.0, 0.0, 0.9]]

    est = SemanticEntropyEstimator(entailment_threshold=0.5)
    assert est._bidirectional_equivalent(MockNLI(), "a", "b") is True


def test_bidirectional_equivalent_one_direction_fails() -> None:
    call_count = 0

    class MockNLI:
        def predict(self, pairs: list[tuple[str, str]]) -> list[list[float]]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [[0.0, 0.0, 0.9]]  # first direction: entails
            return [[0.9, 0.0, 0.1]]  # second direction: contradicts

    est = SemanticEntropyEstimator(entailment_threshold=0.5)
    assert est._bidirectional_equivalent(MockNLI(), "a", "b") is False
