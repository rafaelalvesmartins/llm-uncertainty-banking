# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for the RAISE + UALA tool-gating paths of :class:`UncertaintyGuard`."""

from __future__ import annotations

import pytest

from lub.guard import UncertaintyGuard
from lub.policies import PolicyDecision
from lub.types import UncertaintyResult


class _FixedPipeline:
    """Pipeline stub that always returns the same UncertaintyResult."""

    def __init__(self, confidence: float, answer: str = "ans") -> None:
        self._confidence = confidence
        self._answer = answer
        self.calls: list[str] = []

    def answer(self, prompt: str, **_: object) -> UncertaintyResult:
        self.calls.append(prompt)
        return UncertaintyResult(
            answer=f"{self._answer}({len(self.calls)})",
            confidence=self._confidence,
            raw_scores={"conf": self._confidence},
        )


def test_raise_policy_raises_when_below_threshold() -> None:
    pipe = _FixedPipeline(confidence=0.1)
    guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.RAISE)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="UncertaintyGuard raised"):
        guard("q")


def test_raise_policy_passes_when_above_threshold() -> None:
    pipe = _FixedPipeline(confidence=0.9)
    guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.RAISE)  # type: ignore[arg-type]
    result = guard("q")
    assert result.outcome.decision is PolicyDecision.PASSTHROUGH
    assert result.raw.confidence == 0.9


def test_batch_never_raises_even_with_raise_policy() -> None:
    pipe = _FixedPipeline(confidence=0.1)
    guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.RAISE)  # type: ignore[arg-type]
    outcomes = guard.batch(["q1", "q2", "q3"])
    assert len(outcomes) == 3
    assert all(o.outcome.decision is PolicyDecision.ABSTAIN for o in outcomes)
    assert all(o.output.startswith("[ABSTAIN") for o in outcomes)


def test_gated_tool_call_skips_tool_when_confident() -> None:
    pipe = _FixedPipeline(confidence=0.9)
    guard = UncertaintyGuard(pipe, threshold=0.5)  # type: ignore[arg-type]
    tool_calls: list[str] = []

    def tool(q: str) -> str:
        tool_calls.append(q)
        return "retrieved context"

    result = guard.gated_tool_call("What is CET1?", tool)
    assert tool_calls == []
    assert result.outcome.metadata["tool_invoked"] is False
    assert result.outcome.metadata["uala_gate"] == 0.5


def test_gated_tool_call_invokes_tool_when_uncertain() -> None:
    pipe = _FixedPipeline(confidence=0.1)
    guard = UncertaintyGuard(pipe, threshold=0.5)  # type: ignore[arg-type]
    tool_calls: list[str] = []

    def tool(q: str) -> str:
        tool_calls.append(q)
        return "retrieved context"

    result = guard.gated_tool_call("What is CET1?", tool)
    assert tool_calls == ["What is CET1?"]
    assert result.outcome.metadata["tool_invoked"] is True
    assert result.outcome.metadata["first_pass_confidence"] == 0.1


def test_gated_tool_call_custom_threshold() -> None:
    pipe = _FixedPipeline(confidence=0.7)
    guard = UncertaintyGuard(pipe, threshold=0.5)  # type: ignore[arg-type]
    tool_calls: list[str] = []

    def tool(q: str) -> str:
        tool_calls.append(q)
        return "ctx"

    # 0.7 < 0.9 gate → tool IS invoked even though pipeline threshold is 0.5.
    guard.gated_tool_call("q", tool, uncertainty_threshold=0.9)
    assert tool_calls == ["q"]


def test_gated_tool_call_rejects_bad_threshold() -> None:
    pipe = _FixedPipeline(confidence=0.5)
    guard = UncertaintyGuard(pipe, threshold=0.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="uncertainty_threshold"):
        guard.gated_tool_call("q", lambda _: "x", uncertainty_threshold=1.5)


def test_gated_tool_call_handles_tool_exception() -> None:
    """When the tool function raises, guard returns ABSTAIN instead of crashing."""
    pipe = _FixedPipeline(confidence=0.3)
    guard = UncertaintyGuard(pipe, threshold=0.5)  # type: ignore[arg-type]

    def failing_tool(q: str) -> str:
        raise ConnectionError("database is down")

    result = guard.gated_tool_call("q", failing_tool, uncertainty_threshold=0.5)
    assert result.outcome.decision.value == "abstain"
    assert not result.outcome.passed
    assert "database is down" in result.outcome.reason
    assert result.outcome.metadata.get("tool_error") == "database is down"
    assert result.outcome.metadata.get("tool_invoked") is True
