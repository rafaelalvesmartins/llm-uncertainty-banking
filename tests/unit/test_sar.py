# Copyright 2026 Rafael Martins Alves — Apache-2.0

from __future__ import annotations

import pytest

from lub.uncertainty.sar import TokenSAREstimator
from lub.wrappers.dummy import DummyBackend


def test_sar_returns_valid_confidence(dummy_backend: DummyBackend) -> None:
    est = TokenSAREstimator()
    result = est.score(dummy_backend, "What is CET1?")
    assert 0.0 <= result.confidence <= 1.0
    assert result.answer
    assert "sar" in result.raw_scores
    assert "n_tokens" in result.raw_scores


def test_sar_name_is_token_sar() -> None:
    assert TokenSAREstimator.REGISTRY_KEY == "token_sar"


def test_sar_rejects_bad_threshold() -> None:
    with pytest.raises(ValueError):
        TokenSAREstimator(refusal_threshold=1.5)


def test_sar_should_refuse_when_below_threshold(dummy_backend: DummyBackend) -> None:
    est = TokenSAREstimator(refusal_threshold=0.99)
    result = est.score(dummy_backend, "q")
    assert result.should_refuse or result.confidence >= 0.99


def test_sar_deterministic_across_calls(dummy_backend: DummyBackend) -> None:
    est = TokenSAREstimator()
    r1 = est.score(dummy_backend, "same prompt")
    r2 = est.score(dummy_backend, "same prompt")
    assert r1.confidence == pytest.approx(r2.confidence)
    assert r1.answer == r2.answer
