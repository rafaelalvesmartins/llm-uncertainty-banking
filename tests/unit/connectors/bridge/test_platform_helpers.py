# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for ``lub.connectors.bridge._platform_helpers``."""

from __future__ import annotations

from unittest.mock import MagicMock

from lub.connectors.bridge import EscalationReason
from lub.connectors.bridge._platform_helpers import (
    answers_diverge,
    classify_escalation,
    select_answer,
)
from lub.guard import PolicyDecision


def _verdict(decision: PolicyDecision, output: str = "abstain marker") -> MagicMock:
    """Build a minimal verdict mock with a real PolicyDecision."""
    v = MagicMock()
    v.outcome.decision = decision
    v.output = output
    return v


# ---------------------------------------------------------------------------
# select_answer
# ---------------------------------------------------------------------------


class TestSelectAnswer:
    def test_no_verdict_returns_agent_answer(self) -> None:
        assert select_answer("agent says hi", None) == "agent says hi"

    def test_passthrough_returns_agent_answer(self) -> None:
        v = _verdict(PolicyDecision.PASSTHROUGH)
        assert select_answer("agent says hi", v) == "agent says hi"

    def test_flag_returns_agent_answer(self) -> None:
        v = _verdict(PolicyDecision.FLAG)
        assert select_answer("agent says hi", v) == "agent says hi"

    def test_abstain_returns_verdict_output(self) -> None:
        v = _verdict(PolicyDecision.ABSTAIN, output="[ABSTAIN]")
        assert select_answer("agent says hi", v) == "[ABSTAIN]"


# ---------------------------------------------------------------------------
# answers_diverge
# ---------------------------------------------------------------------------


class TestAnswersDiverge:
    def test_identical_answers_dont_diverge(self) -> None:
        assert answers_diverge("hello world", "hello world") is False

    def test_whitespace_difference_doesnt_diverge(self) -> None:
        assert answers_diverge("hello  world", "hello world") is False

    def test_case_difference_doesnt_diverge(self) -> None:
        assert answers_diverge("Hello World", "hello world") is False

    def test_real_text_difference_diverges(self) -> None:
        assert answers_diverge("hello", "goodbye") is True

    def test_empty_strings_dont_diverge(self) -> None:
        assert answers_diverge("", "") is False


# ---------------------------------------------------------------------------
# classify_escalation
# ---------------------------------------------------------------------------


class TestClassifyEscalation:
    def test_no_verdict_escalates_low_confidence(self) -> None:
        escalated, reason = classify_escalation(None)
        assert escalated is True
        assert reason == EscalationReason.LOW_CONFIDENCE

    def test_passthrough_does_not_escalate(self) -> None:
        v = _verdict(PolicyDecision.PASSTHROUGH)
        escalated, reason = classify_escalation(v)
        assert escalated is False
        assert reason is None

    def test_abstain_escalates_with_policy_abstain(self) -> None:
        v = _verdict(PolicyDecision.ABSTAIN)
        escalated, reason = classify_escalation(v)
        assert escalated is True
        assert reason == EscalationReason.POLICY_ABSTAIN

    def test_flag_escalates_with_policy_flag(self) -> None:
        v = _verdict(PolicyDecision.FLAG)
        escalated, reason = classify_escalation(v)
        assert escalated is True
        assert reason == EscalationReason.POLICY_FLAG

    def test_unknown_decision_falls_back_to_low_confidence(self) -> None:
        # REASK / RAISE / future values fall through to LOW_CONFIDENCE
        # so unknown verdicts never silently bypass human review.
        v = _verdict(PolicyDecision.REASK)
        escalated, reason = classify_escalation(v)
        assert escalated is True
        assert reason == EscalationReason.LOW_CONFIDENCE
