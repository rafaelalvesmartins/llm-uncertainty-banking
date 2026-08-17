# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Chatbot escalation: the low-confidence path must lead somewhere.

Before this feature the agent answered every low-confidence query with
"vou transferir para um especialista" and stopped — no transfer ever
happened and the draft answer was discarded. These tests pin the real
cascade: cheap tier -> stronger tier -> human, with the audit trail and
cost accounting that a BCB 4.893 review needs.
"""

from __future__ import annotations

from typing import Any

import pytest

from lub.connectors.bridge.agents.chatbot import ChatbotAgent


class _Backend:
    """LLM backend double returning a fixed string; counts its calls."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[str] = []

    def complete(self, prompt: str, **kwargs: Any) -> str:
        self.calls.append(prompt)
        return self.response


_SCORES = {"weak-answer": 0.30, "strong-answer": 0.88, "still-weak": 0.41}


def _scorer(prompt: str, answer: str) -> float:
    return _SCORES[answer]


def _agent(*, escalation: str | None, **kwargs: Any) -> ChatbotAgent:
    return ChatbotAgent(
        backend=_Backend("weak-answer"),
        confidence_threshold=0.70,
        confidence_estimator=_scorer,
        escalation_backend=_Backend(escalation) if escalation else None,
        **kwargs,
    )


# --- backward compatibility -------------------------------------------------


def test_without_an_escalation_backend_behaviour_is_unchanged() -> None:
    """No tier-2 configured -> the old canned handoff message, as before."""
    agent = _agent(escalation=None)

    response = agent.answer("posso antecipar meu 13o?")

    assert response.escalated is True
    assert "especialista" in response.answer
    assert response.metadata["original_answer"] == "weak-answer"


# --- the cascade ------------------------------------------------------------


def test_low_confidence_returns_the_escalation_backend_answer() -> None:
    agent = _agent(escalation="strong-answer")

    response = agent.answer("posso antecipar meu 13o?")

    assert response.answer == "strong-answer"
    assert response.confidence == pytest.approx(0.88)
    assert response.escalated is True


def test_low_confidence_no_longer_dead_ends_on_the_canned_message() -> None:
    agent = _agent(escalation="strong-answer")

    response = agent.answer("posso antecipar meu 13o?")

    assert "especialista" not in response.answer


def test_high_confidence_never_calls_the_escalation_backend() -> None:
    """Cost control: the expensive tier stays idle when tier-1 is sure."""
    strong = _Backend("strong-answer")
    agent = ChatbotAgent(
        backend=_Backend("strong-answer"),  # tier-1 already confident
        confidence_threshold=0.70,
        confidence_estimator=_scorer,
        escalation_backend=strong,
    )

    response = agent.answer("qual meu saldo?")

    assert response.escalated is False
    assert response.metadata["resolution"] == "primary"
    assert strong.calls == []


def test_resolution_metadata_names_the_tier_that_answered() -> None:
    agent = _agent(escalation="strong-answer")

    assert agent.answer("pergunta").metadata["resolution"] == "escalation"


def test_escalation_path_records_one_hop_per_tier() -> None:
    agent = _agent(escalation="strong-answer")

    path = agent.answer("pergunta").metadata["escalation_path"]

    assert [hop["name"] for hop in path] == ["primary", "escalation"]
    assert path[0]["passed"] is False
    assert path[1]["passed"] is True
    assert path[0]["confidence"] == pytest.approx(0.30)


def test_cost_accounting_sums_only_the_tiers_actually_called() -> None:
    cheap_only = ChatbotAgent(
        backend=_Backend("strong-answer"),
        confidence_threshold=0.70,
        confidence_estimator=_scorer,
        escalation_backend=_Backend("strong-answer"),
        primary_cost=0.001,
        escalation_cost=0.015,
    )
    both = _agent(escalation="strong-answer", primary_cost=0.001, escalation_cost=0.015)

    assert cheap_only.answer("facil").metadata["total_cost"] == pytest.approx(0.001)
    assert both.answer("dificil").metadata["total_cost"] == pytest.approx(0.016)


# --- human handoff ----------------------------------------------------------


def test_both_tiers_uncertain_hands_to_a_human() -> None:
    agent = _agent(escalation="still-weak")

    response = agent.answer("pergunta impossivel")

    assert response.escalated is True
    assert response.metadata["resolution"] == "human"
    assert response.metadata["human_review_required"] is True
    assert "especialista" in response.answer


def test_the_human_receives_both_drafts() -> None:
    """The reviewer must not have to re-derive what the models said."""
    agent = _agent(escalation="still-weak")

    drafts = agent.answer("pergunta impossivel").metadata["drafts"]

    assert drafts["primary"] == "weak-answer"
    assert drafts["escalation"] == "still-weak"


# --- failure modes ----------------------------------------------------------


def test_tier1_backend_error_still_returns_the_technical_message() -> None:
    class _Broken:
        def complete(self, prompt: str, **kwargs: Any) -> str:
            raise RuntimeError("connection refused")

    agent = ChatbotAgent(
        backend=_Broken(),
        confidence_threshold=0.70,
        confidence_estimator=_scorer,
        escalation_backend=_Backend("strong-answer"),
    )

    response = agent.answer("pergunta")

    assert response.escalated is True
    assert response.confidence == 0.0
    assert "dificuldades tecnicas" in response.answer
