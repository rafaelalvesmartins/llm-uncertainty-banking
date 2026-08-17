# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

from pathlib import Path

import pytest

from lub.types import Generation, TokenLogProbs
from lub.uncertainty.conformal import ConformalEstimator
from lub.wrappers.dummy import DummyBackend


class _ControlledBackend(DummyBackend):
    def __init__(self, prompt_to_lp: dict[str, float]) -> None:
        super().__init__(model_id="controlled")
        self._map = prompt_to_lp

    def generate(self, prompt, n_samples=1, temperature=0.7, max_tokens=256):  # type: ignore[override]
        lp = self._map[prompt]
        return [Generation(text="ans", logprobs=[lp, lp], finish_reason="stop")]

    def logprobs(self, prompt: str, completion: str) -> TokenLogProbs:  # type: ignore[override]
        lp = self._map[prompt]
        return TokenLogProbs(tokens=["a", "b"], logprobs=[lp, lp])


def test_requires_fit_before_score() -> None:
    est = ConformalEstimator(alpha=0.1)
    with pytest.raises(RuntimeError):
        est.score(_ControlledBackend({"x": -1.0}), "x")


def test_fit_threshold_is_deterministic() -> None:
    calibration = {"p1": -1.0, "p2": -2.0, "p3": -3.0, "p4": -4.0, "p5": -5.0}
    backend = _ControlledBackend(calibration)
    est = ConformalEstimator(alpha=0.2)
    est.fit(
        [(p, "gold") for p in calibration],
        backend=backend,
    )
    assert est.threshold is not None
    assert est.n_calibration == 5


def test_roundtrip_json() -> None:
    est = ConformalEstimator(alpha=0.1)
    est.threshold = 1.23
    est.n_calibration = 42
    restored = ConformalEstimator.from_dict(est.to_dict())
    assert restored.alpha == pytest.approx(0.1)
    assert restored.threshold == pytest.approx(1.23)
    assert restored.n_calibration == 42


def test_empty_calibration_rejected() -> None:
    est = ConformalEstimator(alpha=0.1)
    with pytest.raises(ValueError):
        est.fit([], backend=_ControlledBackend({}))


def test_score_inside_threshold() -> None:
    """Test that a conforming example returns high confidence."""
    calibration = {"p1": -1.0, "p2": -1.5, "p3": -2.0}
    backend = _ControlledBackend({**calibration, "q": -1.0})
    est = ConformalEstimator(alpha=0.1)
    est.fit([(p, "gold") for p in calibration], backend=backend)
    result = est.score(backend, "q")
    # q has nonconformity = 1.0 (low), should be inside threshold
    assert result.confidence == pytest.approx(0.9)
    assert result.should_refuse is False
    assert "nonconformity" in result.raw_scores
    assert "threshold" in result.raw_scores


def test_score_outside_threshold() -> None:
    """Test that a non-conforming example returns zero confidence."""
    calibration = {"p1": -1.0, "p2": -1.5, "p3": -2.0}
    # q has very low logprob → high nonconformity
    backend = _ControlledBackend({**calibration, "q": -100.0})
    est = ConformalEstimator(alpha=0.1)
    est.fit([(p, "gold") for p in calibration], backend=backend)
    result = est.score(backend, "q")
    assert result.confidence == 0.0
    assert result.should_refuse is True


def test_score_returns_answer_text() -> None:
    calibration = {"p1": -1.0}
    backend = _ControlledBackend({**calibration, "q": -1.0})
    est = ConformalEstimator(alpha=0.1)
    est.fit([("p1", "gold")], backend=backend)
    result = est.score(backend, "q")
    assert result.answer == "ans"
    assert result.samples == ["ans"]


def test_save_and_load(tmp_path: Path) -> None:
    est = ConformalEstimator(alpha=0.15)
    est.threshold = 2.5
    est.n_calibration = 10
    path = tmp_path / "conf.json"
    est.save(path)
    loaded = ConformalEstimator.load(path)
    assert loaded.alpha == pytest.approx(0.15)
    assert loaded.threshold == pytest.approx(2.5)
    assert loaded.n_calibration == 10


def test_from_dict_rejects_wrong_type() -> None:
    with pytest.raises(ValueError, match="unexpected type"):
        ConformalEstimator.from_dict({"type": "WrongType", "alpha": 0.1})


def test_alpha_validation() -> None:
    with pytest.raises(ValueError):
        ConformalEstimator(alpha=0.0)
    with pytest.raises(ValueError):
        ConformalEstimator(alpha=1.0)


def test_nonconformity_empty_logprobs() -> None:
    """Empty logprobs → inf nonconformity."""
    from lub.uncertainty._conformal_utils import token_logprob_nonconformity

    class EmptyBackend(DummyBackend):
        def logprobs(self, prompt: str, completion: str) -> TokenLogProbs:  # type: ignore[override]
            return TokenLogProbs(tokens=[], logprobs=[])

    result = token_logprob_nonconformity(EmptyBackend(model_id="e"), "p", "c")
    assert result == float("inf")
