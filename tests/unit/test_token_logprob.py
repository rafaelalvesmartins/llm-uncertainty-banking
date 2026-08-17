# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import math

import pytest

from lub.types import Generation
from lub.uncertainty.token_logprob import TokenLogprobEstimator
from lub.wrappers.dummy import DummyBackend


class _FixedBackend(DummyBackend):
    def __init__(self, logprobs: list[float]) -> None:
        super().__init__(model_id="fixed")
        self._fixed = logprobs

    def generate(self, prompt, n_samples=1, temperature=0.7, max_tokens=256):  # type: ignore[override]
        return [Generation(text="42", logprobs=list(self._fixed), finish_reason="stop")]


def test_confidence_matches_exp_mean_logprob() -> None:
    backend = _FixedBackend([-0.1, -0.2, -0.3])
    est = TokenLogprobEstimator(refusal_threshold=0.0)
    result = est.score(backend, "q")
    expected = math.exp(-0.2)
    assert result.confidence == pytest.approx(expected, abs=1e-6)
    assert result.answer == "42"
    assert result.should_refuse is False


def test_empty_logprobs_yield_zero_confidence_and_refusal() -> None:
    backend = _FixedBackend([])
    est = TokenLogprobEstimator(refusal_threshold=0.5)
    result = est.score(backend, "q")
    assert result.confidence == 0.0
    assert result.should_refuse is True


def test_invalid_threshold_rejected() -> None:
    with pytest.raises(ValueError):
        TokenLogprobEstimator(refusal_threshold=1.5)
