# Copyright 2026 Rafael Martins Alves -- Apache-2.0

from __future__ import annotations

import pytest

from lub.uncertainty.ccp import CCPEstimator
from lub.wrappers.dummy import DummyBackend


def test_ccp_returns_valid_confidence(dummy_backend: DummyBackend) -> None:
    est = CCPEstimator()
    result = est.score(dummy_backend, "What is CET1?")
    assert 0.0 <= result.confidence <= 1.0
    assert result.answer
    assert "n_claims" in result.raw_scores
    assert "n_supported" in result.raw_scores
    assert "claim_support_rate" in result.raw_scores


def test_ccp_name() -> None:
    assert CCPEstimator.REGISTRY_KEY == "ccp"


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"refusal_threshold": 1.5}, "refusal_threshold"),
        ({"refusal_threshold": -0.1}, "refusal_threshold"),
        ({"max_claims": 0}, "max_claims"),
        ({"max_claims": -1}, "max_claims"),
    ],
)
def test_ccp_rejects_bad_init_args(kwargs: dict, field: str) -> None:
    with pytest.raises(ValueError, match=field):
        CCPEstimator(**kwargs)


def test_ccp_n_claims_bounded_by_max(dummy_backend: DummyBackend) -> None:
    est = CCPEstimator(max_claims=2)
    result = est.score(dummy_backend, "q")
    assert result.raw_scores["n_claims"] <= 2
