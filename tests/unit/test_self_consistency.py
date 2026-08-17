# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import pytest

from lub.types import Generation
from lub.uncertainty.self_consistency import SelfConsistencyEstimator
from lub.wrappers.dummy import DummyBackend


class _ScriptedBackend(DummyBackend):
    def __init__(self, texts: list[str]) -> None:
        super().__init__(model_id="scripted")
        self._texts = texts

    def generate(self, prompt, n_samples=1, temperature=0.7, max_tokens=256):  # type: ignore[override]
        return [Generation(text=t, logprobs=[-0.5], finish_reason="stop") for t in self._texts]


def test_unanimous_agreement_is_full_confidence() -> None:
    backend = _ScriptedBackend(["Paris", "Paris", "Paris"])
    est = SelfConsistencyEstimator(n_samples=3)
    result = est.score(backend, "capital of France?")
    assert result.answer == "Paris"
    assert result.confidence == pytest.approx(1.0)
    assert result.should_refuse is False


def test_majority_wins_and_confidence_is_fraction() -> None:
    backend = _ScriptedBackend(["Paris", "Paris", "London", "Berlin"])
    est = SelfConsistencyEstimator(n_samples=4, refusal_threshold=0.6)
    result = est.score(backend, "q")
    assert result.answer == "Paris"
    assert result.confidence == pytest.approx(0.5)
    assert result.should_refuse is True


def test_normalizes_case_and_whitespace() -> None:
    backend = _ScriptedBackend(["Yes", "  yes ", "YES"])
    est = SelfConsistencyEstimator(n_samples=3)
    result = est.score(backend, "q")
    assert result.confidence == pytest.approx(1.0)
