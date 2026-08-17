# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from lub.orchestration.swarm import UQSwarm
from lub.types import UncertaintyResult


@dataclass
class _FakeEstimator:
    """Minimal estimator stub that ignores the backend and returns a preset."""

    confidence: float
    answer: str = "shared-ans"

    def score(self, backend: Any, prompt: str, **kwargs: Any) -> UncertaintyResult:
        return UncertaintyResult(answer=self.answer, confidence=self.confidence)


class _FakeBackend:
    pass


def test_fused_confidence_is_weighted_mean() -> None:
    swarm = UQSwarm(
        backend=_FakeBackend(),
        estimators={
            "a": _FakeEstimator(0.4),
            "b": _FakeEstimator(0.8),
        },
        weights={"a": 1.0, "b": 3.0},
    )
    out = swarm.answer("x")
    # normalised weights: 0.25 and 0.75 -> 0.25*0.4 + 0.75*0.8 = 0.70
    assert out.fused.confidence == pytest.approx(0.70)


def test_uniform_weights_default() -> None:
    swarm = UQSwarm(
        backend=_FakeBackend(),
        estimators={"a": _FakeEstimator(0.2), "b": _FakeEstimator(0.6)},
    )
    out = swarm.answer("x")
    assert out.fused.confidence == pytest.approx(0.4)


def test_disagreement_is_zero_when_all_equal() -> None:
    swarm = UQSwarm(
        backend=_FakeBackend(),
        estimators={"a": _FakeEstimator(0.5), "b": _FakeEstimator(0.5)},
    )
    out = swarm.answer("x")
    assert out.fused.raw_scores["method_disagreement"] == pytest.approx(0.0)


def test_disagreement_nonzero_when_split() -> None:
    swarm = UQSwarm(
        backend=_FakeBackend(),
        estimators={"a": _FakeEstimator(0.1), "b": _FakeEstimator(0.9)},
    )
    out = swarm.answer("x")
    assert out.fused.raw_scores["method_disagreement"] > 0.0


def test_per_method_scores_exposed() -> None:
    swarm = UQSwarm(
        backend=_FakeBackend(),
        estimators={"a": _FakeEstimator(0.1), "b": _FakeEstimator(0.9)},
    )
    out = swarm.answer("x")
    assert out.per_method["a"].confidence == 0.1
    assert out.per_method["b"].confidence == 0.9
    assert out.fused.raw_scores["method_a"] == pytest.approx(0.1)
    assert out.fused.raw_scores["method_b"] == pytest.approx(0.9)


def test_empty_estimators_rejected() -> None:
    with pytest.raises(ValueError, match="at least one estimator"):
        UQSwarm(backend=_FakeBackend(), estimators={})


def test_zero_weights_rejected() -> None:
    with pytest.raises(ValueError, match="positive number"):
        UQSwarm(
            backend=_FakeBackend(),
            estimators={"a": _FakeEstimator(0.5)},
            weights={"a": 0.0},
        )


def test_to_dict_is_json_safe() -> None:
    import json

    swarm = UQSwarm(
        backend=_FakeBackend(),
        estimators={"a": _FakeEstimator(0.5), "b": _FakeEstimator(0.7)},
    )
    json.dumps(swarm.answer("x").to_dict())
