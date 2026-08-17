# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Structural protocol compliance tests.

Validates that concrete classes satisfy BackendProto and PipelineProto
at both the structural (isinstance) and behavioral (callable) level.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from lub.types import Generation, TokenLogProbs, UncertaintyResult
from lub.wrappers.dummy import DummyBackend

# ---------------------------------------------------------------------------
# BackendProto
# ---------------------------------------------------------------------------


def test_dummy_backend_satisfies_backend_proto() -> None:
    """DummyBackend structurally satisfies BackendProto."""
    backend = DummyBackend()
    # Structural check: has all three methods with correct signatures.
    assert hasattr(backend, "generate")
    assert hasattr(backend, "logprobs")
    assert hasattr(backend, "embed")
    assert callable(backend.generate)
    assert callable(backend.logprobs)
    assert callable(backend.embed)


def test_dummy_backend_generate_returns_generations() -> None:
    backend = DummyBackend()
    gens = backend.generate("hello", n_samples=3, temperature=0.5)
    assert isinstance(gens, list)
    assert len(gens) == 3
    for g in gens:
        assert isinstance(g, Generation)
        assert isinstance(g.text, str)
        assert g.logprobs is not None


def test_dummy_backend_logprobs_returns_token_logprobs() -> None:
    backend = DummyBackend()
    result = backend.logprobs("hello world", "foo bar")
    assert isinstance(result, TokenLogProbs)
    assert isinstance(result.tokens, list)
    assert isinstance(result.logprobs, list)
    assert len(result.tokens) == len(result.logprobs)


def test_dummy_backend_embed_returns_ndarray() -> None:
    backend = DummyBackend()
    vec = backend.embed("test text")
    assert isinstance(vec, np.ndarray)
    assert vec.ndim == 1
    # Normalized to unit length.
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-6


def test_dummy_backend_generate_rejects_zero_samples() -> None:
    with pytest.raises(ValueError):
        DummyBackend().generate("hello", n_samples=0)


def test_custom_mock_satisfies_backend_proto() -> None:
    """A plain class with the right methods satisfies BackendProto structurally."""

    class MockBackend:
        def generate(
            self, prompt: str, *, n_samples: int = 1,
            temperature: float = 0.7, max_tokens: int = 256,
        ) -> list[Generation]:
            return [Generation(text="mock", logprobs=[-0.5], finish_reason="stop")]

        def logprobs(self, prompt: str, completion: str) -> TokenLogProbs:
            return TokenLogProbs(tokens=["mock"], logprobs=[-0.5])

        def embed(self, text: str) -> np.ndarray[Any, Any]:
            return np.zeros(4)

    mock = MockBackend()
    gens = mock.generate("test")
    assert len(gens) == 1
    assert gens[0].text == "mock"


# ---------------------------------------------------------------------------
# PipelineProto
# ---------------------------------------------------------------------------


def test_uncertainty_pipeline_satisfies_pipeline_proto() -> None:
    """UncertaintyPipeline structurally satisfies PipelineProto."""
    from lub.pipeline import UncertaintyPipeline
    from lub.uncertainty.token_logprob import TokenLogprobEstimator

    pipe = UncertaintyPipeline(
        backend=DummyBackend(),
        estimator=TokenLogprobEstimator(),
    )
    assert hasattr(pipe, "answer")
    assert hasattr(pipe, "batch_answer")
    assert hasattr(pipe, "to_dict")
    assert callable(pipe.answer)
    assert callable(pipe.batch_answer)
    assert callable(pipe.to_dict)


def test_pipeline_answer_returns_uncertainty_result() -> None:
    from lub.pipeline import UncertaintyPipeline
    from lub.uncertainty.token_logprob import TokenLogprobEstimator

    pipe = UncertaintyPipeline(
        backend=DummyBackend(),
        estimator=TokenLogprobEstimator(),
    )
    result = pipe.answer("What is 2+2?")
    assert isinstance(result, UncertaintyResult)
    assert isinstance(result.answer, str)
    assert 0.0 <= result.confidence <= 1.0


def test_pipeline_batch_answer_returns_list() -> None:
    from lub.pipeline import UncertaintyPipeline
    from lub.uncertainty.token_logprob import TokenLogprobEstimator

    pipe = UncertaintyPipeline(
        backend=DummyBackend(),
        estimator=TokenLogprobEstimator(),
    )
    results = pipe.batch_answer(["Q1", "Q2"])
    assert isinstance(results, list)
    assert len(results) == 2
    for r in results:
        assert isinstance(r, UncertaintyResult)


def test_pipeline_to_dict_roundtrip() -> None:
    from lub.pipeline import UncertaintyPipeline
    from lub.uncertainty.token_logprob import TokenLogprobEstimator

    pipe = UncertaintyPipeline(
        backend=DummyBackend(),
        estimator=TokenLogprobEstimator(),
    )
    d = pipe.to_dict()
    assert isinstance(d, dict)
    assert "backend" in d
    assert "estimator" in d
    # Round-trip.
    pipe2 = UncertaintyPipeline.from_dict(d)
    assert pipe2.to_dict() == d
