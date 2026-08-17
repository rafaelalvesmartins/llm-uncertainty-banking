# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for PerplexityEstimator."""

from __future__ import annotations

import math

import pytest

from lub.uncertainty import PerplexityEstimator
from lub.wrappers import DummyBackend


def test_perplexity_returns_valid_result() -> None:
    est = PerplexityEstimator()
    result = est.score(DummyBackend(), "What is CET1?")
    assert 0.0 <= result.confidence <= 1.0
    assert result.answer
    assert "perplexity" in result.raw_scores
    assert "mean_logprob" in result.raw_scores
    assert "n_tokens" in result.raw_scores


def test_perplexity_matches_exp_mean_logprob() -> None:
    est = PerplexityEstimator()
    result = est.score(DummyBackend(), "What is LCR?")
    mean_lp = result.raw_scores["mean_logprob"]
    expected_conf = max(0.0, min(1.0, math.exp(mean_lp)))
    expected_ppl = math.exp(-mean_lp)
    assert result.confidence == pytest.approx(expected_conf, rel=1e-9)
    assert result.raw_scores["perplexity"] == pytest.approx(expected_ppl, rel=1e-9)


def test_perplexity_refusal_threshold_gate() -> None:
    # DummyBackend logprobs are -1.0 per token, so confidence ~= exp(-1) ~= 0.368
    est_strict = PerplexityEstimator(refusal_threshold=0.5)
    result = est_strict.score(DummyBackend(), "q?")
    assert result.should_refuse is True

    est_permissive = PerplexityEstimator(refusal_threshold=0.1)
    result2 = est_permissive.score(DummyBackend(), "q?")
    assert result2.should_refuse is False


def test_perplexity_invalid_threshold() -> None:
    with pytest.raises(ValueError):
        PerplexityEstimator(refusal_threshold=1.5)
