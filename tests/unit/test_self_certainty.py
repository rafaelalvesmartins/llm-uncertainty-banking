# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the SelfCertainty estimator (Huang et al. 2025)."""

from __future__ import annotations

import math

import pytest

from lub.types import Generation
from lub.uncertainty.self_certainty import SelfCertaintyEstimator
from lub.wrappers.dummy import DummyBackend


class _FixedLogprobsBackend(DummyBackend):
    """Return a single generation with a controlled logprob list."""

    # Empty REGISTRY_KEY blocks __init_subclass__ from overwriting
    # DummyBackend's "dummy" slot with this test mock.
    REGISTRY_KEY = ""

    def __init__(self, text: str, logprobs: list[float] | None) -> None:
        super().__init__(model_id="fixed")
        self._text = text
        self._logprobs = logprobs

    def generate(
        self,
        prompt: str,
        n_samples: int = 1,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> list[Generation]:
        return [Generation(text=self._text, logprobs=self._logprobs, finish_reason="stop")]


def test_high_logprob_yields_high_certainty() -> None:
    # logprob = log(0.95) → prob ~ 0.95 → confidence ~ 0.95.
    logp = math.log(0.95)
    backend = _FixedLogprobsBackend("ans", [logp, logp, logp])
    est = SelfCertaintyEstimator()
    result = est.score(backend, "q")
    assert result.confidence == pytest.approx(0.95, abs=1e-3)
    assert result.raw_scores["n_tokens"] == 3.0
    assert result.should_refuse is False


def test_low_logprob_triggers_refusal() -> None:
    logp = math.log(0.1)
    backend = _FixedLogprobsBackend("ans", [logp, logp])
    est = SelfCertaintyEstimator(refusal_threshold=0.5)
    result = est.score(backend, "q")
    assert result.confidence == pytest.approx(0.1, abs=1e-3)
    assert result.should_refuse is True


def test_empty_logprobs_returns_zero_confidence_and_refuses() -> None:
    backend = _FixedLogprobsBackend("ans", [])
    est = SelfCertaintyEstimator(refusal_threshold=0.5)
    result = est.score(backend, "q")
    assert result.confidence == 0.0
    assert result.raw_scores["n_tokens"] == 0.0
    assert result.should_refuse is True


def test_none_logprobs_treated_as_empty() -> None:
    backend = _FixedLogprobsBackend("ans", None)
    est = SelfCertaintyEstimator()
    result = est.score(backend, "q")
    assert result.confidence == 0.0
    assert result.raw_scores["n_tokens"] == 0.0


def test_records_min_and_max_token_prob() -> None:
    backend = _FixedLogprobsBackend("ans", [math.log(0.2), math.log(0.8), math.log(0.5)])
    est = SelfCertaintyEstimator()
    result = est.score(backend, "q")
    assert result.raw_scores["min_token_prob"] == pytest.approx(0.2, abs=1e-3)
    assert result.raw_scores["max_token_prob"] == pytest.approx(0.8, abs=1e-3)
    # Mean of [0.2, 0.8, 0.5] = 0.5
    assert result.confidence == pytest.approx(0.5, abs=1e-3)


def test_invalid_refusal_threshold_rejected() -> None:
    with pytest.raises(ValueError):
        SelfCertaintyEstimator(refusal_threshold=1.2)
    with pytest.raises(ValueError):
        SelfCertaintyEstimator(refusal_threshold=-0.1)
