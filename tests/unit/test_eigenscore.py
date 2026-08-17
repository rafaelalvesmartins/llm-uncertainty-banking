# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for EigenScoreEstimator (Lin et al. 2023)."""

from __future__ import annotations

import numpy as np
import pytest

from lub.types import Generation, TokenLogProbs
from lub.uncertainty import EigenScoreEstimator
from lub.wrappers import DummyBackend
from lub.wrappers.base import ModelBackend


class _IdenticalAnswersBackend(ModelBackend):
    """Every sample produces the same text and the same embedding."""

    def __init__(self) -> None:
        super().__init__("identical")
        self._vec = np.array([1.0, 0.0, 0.0, 0.0])

    def generate(self, prompt, n_samples=1, temperature=0.7, max_tokens=256):
        return [
            Generation(text="same", logprobs=[-1.0], finish_reason="stop")
            for _ in range(n_samples)
        ]

    def logprobs(self, prompt, completion):
        return TokenLogProbs(tokens=[completion], logprobs=[-1.0])

    def embed(self, text):
        return self._vec.copy()


class _DiverseAnswersBackend(ModelBackend):
    """Each sample gets a distinct orthogonal unit embedding."""

    def __init__(self, dim: int = 8) -> None:
        super().__init__("diverse")
        self._dim = dim
        self._calls = 0

    def generate(self, prompt, n_samples=1, temperature=0.7, max_tokens=256):
        return [
            Generation(text=f"answer-{i}", logprobs=[-1.0], finish_reason="stop")
            for i in range(n_samples)
        ]

    def logprobs(self, prompt, completion):
        return TokenLogProbs(tokens=[completion], logprobs=[-1.0])

    def embed(self, text):
        idx = int(text.split("-")[-1])
        v = np.zeros(self._dim)
        v[idx % self._dim] = 1.0
        return v


def test_eigenscore_runs_against_dummy_backend() -> None:
    est = EigenScoreEstimator(n_samples=4)
    result = est.score(DummyBackend(), "q?")
    assert 0.0 <= result.confidence <= 1.0
    assert "eigen_score" in result.raw_scores
    assert len(result.samples or []) == 4


def test_eigenscore_identical_answers_high_confidence() -> None:
    est = EigenScoreEstimator(n_samples=5)
    result = est.score(_IdenticalAnswersBackend(), "q?")
    # Centered Gram is zero matrix -> all eigvals floor at 1e-12 ->
    # confidence saturates at 1.0.
    assert result.confidence == pytest.approx(1.0, rel=1e-6)
    assert result.should_refuse is False


def test_eigenscore_diverse_answers_lower_confidence() -> None:
    est = EigenScoreEstimator(n_samples=5)
    result_div = est.score(_DiverseAnswersBackend(dim=8), "q?")
    result_id = est.score(_IdenticalAnswersBackend(), "q?")
    assert result_div.confidence < result_id.confidence
    assert result_div.confidence < 1.0


def test_eigenscore_invalid_config() -> None:
    with pytest.raises(ValueError):
        EigenScoreEstimator(n_samples=1)
    with pytest.raises(ValueError):
        EigenScoreEstimator(temperature=0.0)
    with pytest.raises(ValueError):
        EigenScoreEstimator(refusal_threshold=-0.1)
