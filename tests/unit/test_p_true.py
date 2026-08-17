# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for PTrueEstimator (Kadavath et al. 2022)."""

from __future__ import annotations

import pytest

from lub.types import Generation, TokenLogProbs
from lub.uncertainty import PTrueEstimator
from lub.wrappers import DummyBackend
from lub.wrappers.base import ModelBackend


class _WhiteboxStubBackend(ModelBackend):
    """Backend that returns fixed logprobs for "True" vs "False"."""

    def __init__(self, true_logprob: float, false_logprob: float) -> None:
        super().__init__("stub-whitebox")
        self._true_lp = true_logprob
        self._false_lp = false_logprob

    def generate(
        self,
        prompt: str,
        n_samples: int = 1,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> list[Generation]:
        return [Generation(text="stub-answer", logprobs=[-1.0])]

    def logprobs(self, prompt: str, completion: str) -> TokenLogProbs:
        if completion.strip() == "True":
            return TokenLogProbs(tokens=["True"], logprobs=[self._true_lp])
        if completion.strip() == "False":
            return TokenLogProbs(tokens=["False"], logprobs=[self._false_lp])
        return TokenLogProbs(tokens=[], logprobs=[])

    def embed(self, text: str):  # pragma: no cover - unused in these tests
        raise NotImplementedError


class _BlackboxStubBackend(ModelBackend):
    """Backend whose judge samples are majority True."""

    def __init__(self, true_count: int, false_count: int) -> None:
        super().__init__("stub-blackbox")
        self._true = true_count
        self._false = false_count

    def generate(
        self,
        prompt: str,
        n_samples: int = 1,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> list[Generation]:
        if "Is the proposed answer correct" not in prompt:
            return [Generation(text="stub-answer", logprobs=[-1.0])]
        out: list[Generation] = []
        for _ in range(self._true):
            out.append(Generation(text="True", logprobs=[-0.1]))
        for _ in range(self._false):
            out.append(Generation(text="False", logprobs=[-0.1]))
        return out[:n_samples] if len(out) >= n_samples else out

    def logprobs(self, prompt: str, completion: str) -> TokenLogProbs:
        raise NotImplementedError

    def embed(self, text: str):  # pragma: no cover
        raise NotImplementedError


def test_p_true_whitebox_path_high_confidence() -> None:
    est = PTrueEstimator()
    # true_lp >> false_lp -> p_true ~ 1.0
    result = est.score(_WhiteboxStubBackend(true_logprob=-0.1, false_logprob=-5.0), "q?")
    assert result.raw_scores["path_is_whitebox"] == 1.0
    assert result.confidence > 0.95
    assert result.should_refuse is False


def test_p_true_whitebox_path_low_confidence() -> None:
    est = PTrueEstimator()
    # false_lp >> true_lp -> p_true ~ 0.0
    result = est.score(_WhiteboxStubBackend(true_logprob=-5.0, false_logprob=-0.1), "q?")
    assert result.raw_scores["path_is_whitebox"] == 1.0
    assert result.confidence < 0.05
    assert result.should_refuse is True


def test_p_true_blackbox_fallback_majority_true() -> None:
    est = PTrueEstimator(n_blackbox_samples=5)
    result = est.score(_BlackboxStubBackend(true_count=4, false_count=1), "q?")
    assert result.raw_scores["path_is_whitebox"] == 0.0
    assert result.confidence == pytest.approx(0.8, rel=1e-6)
    assert result.raw_scores["blackbox_agreement"] == pytest.approx(1.0, rel=1e-6)


def test_p_true_blackbox_fallback_majority_false() -> None:
    est = PTrueEstimator(n_blackbox_samples=5)
    result = est.score(_BlackboxStubBackend(true_count=1, false_count=4), "q?")
    assert result.confidence == pytest.approx(0.2, rel=1e-6)
    assert result.should_refuse is True


def test_p_true_runs_against_dummy_backend() -> None:
    # DummyBackend has logprobs that aren't decisive; just verify it doesn't crash
    est = PTrueEstimator(n_blackbox_samples=3)
    result = est.score(DummyBackend(), "What is CET1?")
    assert 0.0 <= result.confidence <= 1.0
    assert "p_true" in result.raw_scores


def test_p_true_invalid_config() -> None:
    with pytest.raises(ValueError):
        PTrueEstimator(n_blackbox_samples=0)
    with pytest.raises(ValueError):
        PTrueEstimator(temperature=0.0)
    with pytest.raises(ValueError):
        PTrueEstimator(refusal_threshold=2.0)
