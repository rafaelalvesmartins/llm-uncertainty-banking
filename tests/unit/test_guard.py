# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import json
from typing import Any

import pytest

from lub.guard import GuardResult, UncertaintyGuard
from lub.policies import PolicyDecision
from lub.types import UncertaintyResult


class _FakePipeline:
    """Minimal UncertaintyPipeline stand-in for hermetic tests."""

    def __init__(self, answer: str, confidence: float) -> None:
        self._answer = answer
        self._confidence = confidence

    def answer(self, prompt: str, **kwargs: Any) -> UncertaintyResult:
        return UncertaintyResult(
            answer=self._answer,
            confidence=self._confidence,
            raw_scores={"agreement": self._confidence},
        )


def test_high_confidence_passes_with_passthrough() -> None:
    pipe = _FakePipeline(answer="4.5%", confidence=0.9)
    guard = UncertaintyGuard(pipe, threshold=0.5)  # type: ignore[arg-type]
    result = guard("q")
    assert isinstance(result, GuardResult)
    assert result.outcome.passed is True
    assert result.outcome.decision is PolicyDecision.PASSTHROUGH
    assert result.output == "4.5%"
    assert result.rmf_subcategory.startswith("GOVERN")


def test_low_confidence_abstains_by_default() -> None:
    pipe = _FakePipeline(answer="guess", confidence=0.1)
    guard = UncertaintyGuard(pipe, threshold=0.8)  # type: ignore[arg-type]
    result = guard("q")
    assert result.outcome.decision is PolicyDecision.ABSTAIN
    assert result.outcome.passed is False
    assert "[ABSTAIN" in result.output
    assert result.raw.answer == "guess"  # raw answer preserved
    assert result.rmf_subcategory == "MANAGE 2.3"


def test_low_confidence_flag_keeps_answer() -> None:
    pipe = _FakePipeline(answer="maybe", confidence=0.3)
    guard = UncertaintyGuard(pipe, threshold=0.8, on_fail=PolicyDecision.FLAG)  # type: ignore[arg-type]
    result = guard("q")
    assert result.outcome.decision is PolicyDecision.FLAG
    assert result.output == "maybe"
    assert result.rmf_subcategory == "MANAGE 2.4"


def test_raise_policy_raises_on_low_confidence() -> None:
    pipe = _FakePipeline(answer="x", confidence=0.1)
    guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.RAISE)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        guard("q")


def test_batch_swallows_raise_into_abstain() -> None:
    pipe = _FakePipeline(answer="x", confidence=0.1)
    guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.RAISE)  # type: ignore[arg-type]
    results = guard.batch(["q1", "q2"])
    assert len(results) == 2
    assert all(r.outcome.decision is PolicyDecision.ABSTAIN for r in results)


def test_invalid_threshold_rejected() -> None:
    pipe = _FakePipeline(answer="x", confidence=0.5)
    with pytest.raises(ValueError):
        UncertaintyGuard(pipe, threshold=1.5)  # type: ignore[arg-type]


def test_invalid_on_fail_type_rejected() -> None:
    pipe = _FakePipeline(answer="x", confidence=0.5)
    with pytest.raises(TypeError):
        UncertaintyGuard(pipe, on_fail="abstain")  # type: ignore[arg-type]


def test_to_dict_is_json_serializable() -> None:
    pipe = _FakePipeline(answer="ok", confidence=0.9)
    guard = UncertaintyGuard(pipe, threshold=0.5)  # type: ignore[arg-type]
    result = guard("q")
    blob = json.dumps(result.to_dict(), sort_keys=True)
    parsed = json.loads(blob)
    assert parsed["outcome"]["decision"] == "passthrough"
    assert parsed["raw"]["answer"] == "ok"


# ── REASK policy tests ──────────────────────────────────────────────


class _ReaskPipeline:
    """Pipeline that returns low confidence on first call, high on retry."""

    def __init__(self, retry_confidence: float = 0.9) -> None:
        self._calls = 0
        self._retry_confidence = retry_confidence

    def answer(self, prompt: str, **kwargs: Any) -> UncertaintyResult:
        self._calls += 1
        if self._calls == 1:
            return UncertaintyResult(
                answer="unsure",
                confidence=0.2,
                raw_scores={"agreement": 0.2},
            )
        return UncertaintyResult(
            answer="confident answer",
            confidence=self._retry_confidence,
            raw_scores={"agreement": self._retry_confidence},
        )


def test_reask_retries_and_succeeds_on_higher_confidence() -> None:
    """REASK: retry succeeds when second pass meets threshold."""
    pipe = _ReaskPipeline(retry_confidence=0.9)
    guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
    result = guard("q")
    assert result.outcome.decision is PolicyDecision.REASK
    assert result.outcome.passed is True
    assert result.output == "confident answer"
    assert result.outcome.metadata["reask_attempted"] is True
    assert result.outcome.metadata["reask_succeeded"] is True
    assert result.outcome.metadata["first_pass_confidence"] == 0.2
    assert result.rmf_subcategory == "MANAGE 2.4"


def test_reask_falls_through_to_abstain_when_retry_also_fails() -> None:
    """REASK: both passes fail -> fall through to ABSTAIN."""
    pipe = _ReaskPipeline(retry_confidence=0.3)  # still below threshold
    guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
    result = guard("q")
    assert result.outcome.decision is PolicyDecision.ABSTAIN
    assert result.outcome.passed is False
    assert "[ABSTAIN" in result.output
    assert result.outcome.metadata["reask_attempted"] is True
    assert result.outcome.metadata["reask_succeeded"] is False


def test_reask_uses_custom_abstain_marker_on_fallthrough() -> None:
    """REASK fallthrough to ABSTAIN respects custom abstain_marker."""
    pipe = _ReaskPipeline(retry_confidence=0.1)
    guard = UncertaintyGuard(
        pipe, threshold=0.5,
        on_fail=PolicyDecision.REASK,
        abstain_marker="CUSTOM_REFUSE",
    )  # type: ignore[arg-type]
    result = guard("q")
    assert result.output == "CUSTOM_REFUSE"
    assert result.outcome.decision is PolicyDecision.ABSTAIN
