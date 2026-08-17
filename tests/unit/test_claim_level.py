# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for claim-level uncertainty scoring (Fadeeva et al. 2024)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lub.types import Generation, UncertaintyResult
from lub.uncertainty.base import Estimator
from lub.uncertainty.claim_level import ClaimLevelEstimator, extract_numeric_claims
from lub.wrappers.base import ModelBackend
from lub.wrappers.dummy import DummyBackend

# --- extract_numeric_claims ------------------------------------------


def test_extract_finds_percent_claim() -> None:
    claims = extract_numeric_claims("The CET1 ratio is 4.5%.")
    assert "4.5%" in [c.replace(" ", "") for c in claims]


def test_extract_finds_multiple_claims() -> None:
    text = "CET1 is 4.5%, total capital is 8%, and LCR is 100%."
    claims = extract_numeric_claims(text)
    stripped = {c.replace(" ", "") for c in claims}
    assert "4.5%" in stripped
    assert "8%" in stripped
    assert "100%" in stripped


def test_extract_returns_empty_on_pure_prose() -> None:
    assert extract_numeric_claims("A capital ratio without any numbers.") == []


def test_extract_handles_currency() -> None:
    claims = extract_numeric_claims("Total exposure was $1,200.")
    assert any("1,200" in c for c in claims)


# --- ClaimLevelEstimator ---------------------------------------------


class _ScriptedBackend(DummyBackend):
    """Return a scripted sequence of texts across successive calls."""

    # Empty REGISTRY_KEY blocks __init_subclass__ from overwriting
    # DummyBackend's "dummy" slot with this test mock.
    REGISTRY_KEY = ""

    def __init__(self, texts: list[str]) -> None:
        super().__init__(model_id="scripted")
        self._iter: Iterator[str] = iter(texts)

    def generate(
        self,
        prompt: str,
        n_samples: int = 1,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> list[Generation]:
        try:
            text = next(self._iter)
        except StopIteration:
            text = ""
        return [Generation(text=text, logprobs=[-0.5], finish_reason="stop")]


class _FixedConfidenceEstimator(Estimator):
    """Returns the same confidence for every prompt — useful for isolating
    the aggregation logic from the base estimator's own scoring."""

    NAME = "fixed"

    def __init__(self, confidences: list[float]) -> None:
        self._iter = iter(confidences)

    def score(
        self,
        backend: ModelBackend,
        prompt: str,
        **kwargs: Any,
    ) -> UncertaintyResult:
        try:
            c = next(self._iter)
        except StopIteration:
            c = 0.5
        return UncertaintyResult(answer="yes", confidence=c)


def test_min_aggregation_takes_weakest_claim() -> None:
    # Answer contains 3 numeric claims; base estimator returns 0.9, 0.4, 0.7.
    # Min should be 0.4. We avoid names containing digits (CET1, IRB) because
    # the regex extracts embedded digits as claims.
    backend = _ScriptedBackend(
        ["The core ratio is 4.5%, the liquidity ratio is 100%, and leverage is 3%."]
    )
    base = _FixedConfidenceEstimator([0.9, 0.4, 0.7])
    est = ClaimLevelEstimator(base_estimator=base, aggregation="min")
    result = est.score(backend, "What are the Basel III ratios?")
    assert result.confidence == pytest.approx(0.4)
    assert result.raw_scores["claim_count"] == 3.0
    assert result.raw_scores["min_claim_confidence"] == pytest.approx(0.4)


def test_mean_aggregation_averages_claim_confidences() -> None:
    backend = _ScriptedBackend(["The core ratio is 4.5% and total capital is 8%."])
    base = _FixedConfidenceEstimator([0.6, 0.8])
    est = ClaimLevelEstimator(base_estimator=base, aggregation="mean")
    result = est.score(backend, "q")
    assert result.confidence == pytest.approx(0.7)
    assert result.raw_scores["claim_count"] == 2.0


def test_no_claims_falls_through_to_base_estimator() -> None:
    backend = _ScriptedBackend(["Plain prose answer with no numbers."])
    base = _FixedConfidenceEstimator([0.55])
    est = ClaimLevelEstimator(base_estimator=base, aggregation="min")
    result = est.score(backend, "q")
    # Base was called once for the fallthrough path.
    assert result.confidence == pytest.approx(0.55)
    assert result.raw_scores["claim_count"] == 0.0


def test_refusal_triggers_below_threshold() -> None:
    backend = _ScriptedBackend(["The core ratio is 4.5%."])
    base = _FixedConfidenceEstimator([0.2])
    est = ClaimLevelEstimator(
        base_estimator=base, aggregation="min", refusal_threshold=0.5,
    )
    result = est.score(backend, "q")
    assert result.should_refuse is True


def test_invalid_aggregation_rejected() -> None:
    with pytest.raises(ValueError):
        ClaimLevelEstimator(
            base_estimator=_FixedConfidenceEstimator([0.5]),
            aggregation="median",  # type: ignore[arg-type]
        )


def test_invalid_refusal_threshold_rejected() -> None:
    with pytest.raises(ValueError):
        ClaimLevelEstimator(
            base_estimator=_FixedConfidenceEstimator([0.5]),
            refusal_threshold=1.5,
        )


def test_claim_details_recorded_in_diagnostics() -> None:
    backend = _ScriptedBackend(["Core ratio is 4.5% and liquidity is 100%."])
    base = _FixedConfidenceEstimator([0.7, 0.3])
    est = ClaimLevelEstimator(base_estimator=base, aggregation="mean")
    result = est.score(backend, "q")
    claims = result.diagnostics["claims"]
    assert isinstance(claims, list)
    assert len(claims) == 2
    assert claims[0]["confidence"] == pytest.approx(0.7)
    assert claims[1]["confidence"] == pytest.approx(0.3)
