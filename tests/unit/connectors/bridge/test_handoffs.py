# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for ``lub.connectors.bridge.handoffs``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from lub.connectors.bridge.handoffs import (
    AgentResponse,
    HandoffableAgent,
    HandoffChain,
    HandoffLoopError,
    MaxHopsExceededError,
    run_with_handoffs,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class StringAgent:
    """Returns a fixed string answer."""

    name: str
    answer: str

    def handle(self, query: str, context: dict[str, Any]) -> str:
        return self.answer


@dataclass
class StructuredAgent:
    """Returns an AgentResponse with metadata."""

    name: str
    answer: str
    confidence: float = 0.9
    extra_metadata: dict[str, Any] | None = None

    def handle(self, query: str, context: dict[str, Any]) -> AgentResponse:
        return AgentResponse(
            answer=self.answer,
            confidence=self.confidence,
            metadata=self.extra_metadata or {},
        )


@dataclass
class HandoffAgent:
    """Hands off to a specific target agent."""

    name: str
    target: HandoffableAgent
    reason: str = ""

    def handle(self, query: str, context: dict[str, Any]) -> HandoffableAgent:
        if self.reason:
            context["handoff_reason"] = self.reason
        return self.target


@dataclass
class ConditionalAgent:
    """Hands off if query contains a keyword; otherwise answers."""

    name: str
    keyword: str
    target: HandoffableAgent
    fallback_answer: str = "default"

    def handle(self, query: str, context: dict[str, Any]) -> Any:
        if self.keyword in query.lower():
            context["handoff_reason"] = f"detected '{self.keyword}'"
            return self.target
        return self.fallback_answer


@dataclass
class BadAgent:
    name: str

    def handle(self, query: str, context: dict[str, Any]) -> Any:
        return 42  # neither str, AgentResponse, nor HandoffableAgent


# ---------------------------------------------------------------------------
# Basic single-agent runs
# ---------------------------------------------------------------------------


class TestSingleAgent:
    def test_returns_string_directly(self) -> None:
        agent = StringAgent(name="bot", answer="ola")
        chain = run_with_handoffs(agent, "qual saldo?")
        assert chain.final_answer == "ola"
        assert chain.final_agent == "bot"
        assert chain.hop_count == 0
        assert chain.confidence == 1.0

    def test_returns_structured_response(self) -> None:
        agent = StructuredAgent(name="bot", answer="ok", confidence=0.85)
        chain = run_with_handoffs(agent, "qual saldo?")
        assert chain.final_answer == "ok"
        assert chain.confidence == 0.85
        assert chain.hop_count == 0

    def test_metadata_propagates(self) -> None:
        agent = StructuredAgent(
            name="bot",
            answer="ok",
            extra_metadata={"intent": "balance"},
        )
        chain = run_with_handoffs(agent, "qual saldo?")
        assert chain.metadata["intent"] == "balance"


# ---------------------------------------------------------------------------
# Handoff chains
# ---------------------------------------------------------------------------


class TestHandoffs:
    def test_single_handoff(self) -> None:
        target = StringAgent(name="payments", answer="paid")
        first = HandoffAgent(name="chatbot", target=target, reason="payment intent")
        chain = run_with_handoffs(first, "pagar pix")

        assert chain.final_answer == "paid"
        assert chain.final_agent == "payments"
        assert chain.hop_count == 1
        assert chain.hops[0].from_agent == "chatbot"
        assert chain.hops[0].to_agent == "payments"
        assert chain.hops[0].reason == "payment intent"

    def test_two_handoffs(self) -> None:
        third = StringAgent(name="agent3", answer="final")
        second = HandoffAgent(name="agent2", target=third)
        first = HandoffAgent(name="agent1", target=second)
        chain = run_with_handoffs(first, "query")

        assert chain.final_answer == "final"
        assert chain.final_agent == "agent3"
        assert chain.hop_count == 2
        assert [h.to_agent for h in chain.hops] == ["agent2", "agent3"]

    def test_conditional_handoff_when_keyword_matches(self) -> None:
        target = StringAgent(name="payments", answer="paid")
        first = ConditionalAgent(name="chatbot", keyword="pix", target=target)
        chain = run_with_handoffs(first, "pagar pix")
        assert chain.final_agent == "payments"
        assert chain.hop_count == 1

    def test_conditional_no_handoff_when_no_keyword(self) -> None:
        target = StringAgent(name="payments", answer="paid")
        first = ConditionalAgent(
            name="chatbot",
            keyword="pix",
            target=target,
            fallback_answer="nothing to pay",
        )
        chain = run_with_handoffs(first, "qual saldo?")
        assert chain.final_agent == "chatbot"
        assert chain.final_answer == "nothing to pay"
        assert chain.hop_count == 0

    def test_handoff_callback_invoked(self) -> None:
        target = StringAgent(name="t", answer="ok")
        first = HandoffAgent(name="f", target=target)
        events = []
        run_with_handoffs(first, "q", on_handoff=events.append)
        assert len(events) == 1
        assert events[0].from_agent == "f"
        assert events[0].to_agent == "t"


# ---------------------------------------------------------------------------
# Limits & errors
# ---------------------------------------------------------------------------


class TestLimits:
    def test_max_hops_exceeded_raises(self) -> None:
        # Build chain a -> b -> c -> d, but max_hops=2
        d = StringAgent(name="d", answer="final")
        c = HandoffAgent(name="c", target=d)
        b = HandoffAgent(name="b", target=c)
        a = HandoffAgent(name="a", target=b)
        with pytest.raises(MaxHopsExceededError):
            run_with_handoffs(a, "q", max_hops=2)

    def test_loop_detected(self) -> None:
        b = HandoffAgent(name="b", target=None)  # type: ignore[arg-type]
        a = HandoffAgent(name="a", target=b)
        b.target = a  # creates a -> b -> a cycle
        with pytest.raises(HandoffLoopError, match="cycle"):
            run_with_handoffs(a, "q")

    def test_invalid_return_type_raises(self) -> None:
        bad = BadAgent(name="bad")
        with pytest.raises(TypeError, match="HandoffableAgent"):
            run_with_handoffs(bad, "q")


# ---------------------------------------------------------------------------
# Context propagation
# ---------------------------------------------------------------------------


class TestContext:
    def test_context_passed_to_agents(self) -> None:
        seen: list[dict[str, Any]] = []

        @dataclass
        class CtxAgent:
            name: str

            def handle(self, query: str, context: dict[str, Any]) -> str:
                seen.append(dict(context))
                return "ok"

        agent = CtxAgent(name="x")
        run_with_handoffs(agent, "q", context={"customer_id": "c-123"})
        assert seen[0]["customer_id"] == "c-123"

    def test_handoff_reason_cleared_after_consumption(self) -> None:
        """An agent that hands off sets context['handoff_reason']; the next
        agent should NOT see it (it was for the handoff event, not state)."""

        seen: list[dict[str, Any]] = []

        @dataclass
        class CtxAgent:
            name: str

            def handle(self, query: str, context: dict[str, Any]) -> str:
                seen.append(dict(context))
                return "final"

        target = CtxAgent(name="t")
        first = HandoffAgent(name="f", target=target, reason="testing")
        run_with_handoffs(first, "q")
        # Target agent should not see handoff_reason in its context.
        assert "handoff_reason" not in seen[0]


# ---------------------------------------------------------------------------
# HandoffChain output
# ---------------------------------------------------------------------------


class TestHandoffChainOutput:
    def test_duration_is_positive(self) -> None:
        agent = StringAgent(name="x", answer="ok")
        chain = run_with_handoffs(agent, "q")
        assert chain.total_duration_ms >= 0

    def test_returns_handoff_chain_instance(self) -> None:
        agent = StringAgent(name="x", answer="ok")
        chain = run_with_handoffs(agent, "q")
        assert isinstance(chain, HandoffChain)
