# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for lub.agents.chatbot module."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from lub.connectors.bridge.agents.chatbot import (
    ChatbotAgent,
    ChatResponse,
    Intent,
)


class FakeBackend:
    """In-memory LLM backend for tests."""

    def __init__(self, response: str = "Your balance is R$ 1,000.00.") -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def complete(self, prompt: str, **kwargs: Any) -> str:
        self.calls.append((prompt, kwargs))
        return self.response


class FailingBackend:
    """Backend that always raises to exercise error paths."""

    def complete(self, prompt: str, **kwargs: Any) -> str:
        raise RuntimeError("backend down")


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def agent(backend: FakeBackend) -> ChatbotAgent:
    return ChatbotAgent(backend=backend, confidence_threshold=0.7)


# ---------------------------------------------------------------------------
# ChatResponse
# ---------------------------------------------------------------------------


class TestChatResponse:
    def test_to_dict_round_trip_fields(self) -> None:
        resp = ChatResponse(
            answer="hello",
            confidence=0.9,
            intent=Intent.BALANCE,
            escalated=False,
            session_id="sess-1",
            metadata={"channel": "app"},
        )
        d = resp.to_dict()
        assert d == {
            "answer": "hello",
            "confidence": 0.9,
            "intent": "balance",
            "escalated": False,
            "session_id": "sess-1",
            "metadata": {"channel": "app"},
        }

    def test_to_dict_serializes_intent_enum_as_value(self) -> None:
        resp = ChatResponse(answer="x", confidence=0.5, intent=Intent.PIX)
        d = resp.to_dict()
        assert d["intent"] == "pix"
        assert isinstance(d["intent"], str)

    def test_confidence_can_be_zero(self) -> None:
        resp = ChatResponse(answer="", confidence=0.0, intent=Intent.GENERAL)
        assert resp.confidence == 0.0
        assert 0.0 <= resp.confidence <= 1.0

    def test_confidence_can_be_one(self) -> None:
        resp = ChatResponse(answer="x", confidence=1.0, intent=Intent.GENERAL)
        assert resp.confidence == 1.0
        assert 0.0 <= resp.confidence <= 1.0

    def test_default_metadata_is_independent_per_instance(self) -> None:
        a = ChatResponse(answer="a", confidence=0.5, intent=Intent.GENERAL)
        b = ChatResponse(answer="b", confidence=0.5, intent=Intent.GENERAL)
        a.metadata["k"] = "v"
        assert b.metadata == {}

    def test_frozen_dataclass_rejects_mutation(self) -> None:
        resp = ChatResponse(answer="x", confidence=0.5, intent=Intent.GENERAL)
        with pytest.raises(Exception):
            resp.answer = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------


class TestClassifyIntent:
    @pytest.mark.parametrize(
        "query,expected",
        [
            ("Qual meu saldo?", Intent.BALANCE),
            ("What is my balance?", Intent.BALANCE),
            ("Quero transferir 100 reais", Intent.TRANSFER),
            ("Send TED to my brother", Intent.TRANSFER),
            ("Preciso de um emprestimo", Intent.LOAN),
            ("I want credit", Intent.LOAN),
            ("Tenho uma reclamacao", Intent.COMPLAINT),
            ("Quero investir em CDB", Intent.INVESTMENT),
            ("Cadastrar chave pix", Intent.PIX),
            ("Limite do meu cartao", Intent.CARD),
        ],
    )
    def test_keyword_routes_to_expected_intent(
        self, agent: ChatbotAgent, query: str, expected: Intent
    ) -> None:
        assert agent.classify_intent(query) == expected

    def test_unknown_query_falls_back_to_general(self, agent: ChatbotAgent) -> None:
        assert agent.classify_intent("Bom dia, tudo bem?") == Intent.GENERAL

    def test_empty_query_falls_back_to_general(self, agent: ChatbotAgent) -> None:
        assert agent.classify_intent("") == Intent.GENERAL

    def test_classification_is_case_insensitive(self, agent: ChatbotAgent) -> None:
        assert agent.classify_intent("SALDO POR FAVOR") == Intent.BALANCE


# ---------------------------------------------------------------------------
# Confidence estimation
# ---------------------------------------------------------------------------


class TestEstimateConfidence:
    def test_empty_answer_returns_low_confidence(self, agent: ChatbotAgent) -> None:
        c = agent._estimate_confidence("", Intent.GENERAL)
        assert c == pytest.approx(0.1)
        assert 0.0 <= c <= 1.0

    def test_short_answer_returns_low_confidence(self, agent: ChatbotAgent) -> None:
        c = agent._estimate_confidence("ok", Intent.GENERAL)
        assert c == pytest.approx(0.1)

    def test_hedged_answer_returns_medium_confidence(
        self, agent: ChatbotAgent
    ) -> None:
        c = agent._estimate_confidence(
            "Nao tenho certeza, mas talvez seja 100 reais.", Intent.BALANCE
        )
        assert c == pytest.approx(0.4)
        assert 0.0 <= c <= 1.0

    def test_confident_answer_returns_high_confidence(
        self, agent: ChatbotAgent
    ) -> None:
        c = agent._estimate_confidence(
            "Seu saldo atual e R$ 1.234,56.", Intent.BALANCE
        )
        assert c == pytest.approx(0.85)
        assert 0.0 <= c <= 1.0

    def test_all_branches_stay_in_unit_interval(self, agent: ChatbotAgent) -> None:
        samples = [
            "",
            "short",
            "I'm not sure about that",
            "A long confident answer that contains no hedging markers at all.",
        ]
        for s in samples:
            c = agent._estimate_confidence(s, Intent.GENERAL)
            assert 0.0 <= c <= 1.0


# ---------------------------------------------------------------------------
# answer() — guardrail behavior
# ---------------------------------------------------------------------------


class TestAnswer:
    def test_high_confidence_passes_through(self, backend: FakeBackend) -> None:
        backend.response = "Seu saldo e R$ 5.000,00 disponivel para saque."
        agent = ChatbotAgent(backend=backend, confidence_threshold=0.7)
        resp = agent.answer("Qual meu saldo?", session_id="s1")
        assert resp.escalated is False
        assert resp.answer == backend.response
        assert resp.intent == Intent.BALANCE
        assert resp.confidence >= 0.7
        assert resp.session_id == "s1"

    def test_low_confidence_escalates(self, backend: FakeBackend) -> None:
        backend.response = "Nao tenho certeza, talvez seja isso."
        agent = ChatbotAgent(backend=backend, confidence_threshold=0.7)
        resp = agent.answer("Qual meu saldo?")
        assert resp.escalated is True
        assert resp.confidence < 0.7
        assert "especialista" in resp.answer.lower() or "transferir" in resp.answer.lower()
        assert resp.metadata.get("original_answer") == backend.response

    def test_threshold_boundary_below_escalates(self, backend: FakeBackend) -> None:
        backend.response = "Seu saldo e R$ 100,00 disponivel."
        agent = ChatbotAgent(backend=backend, confidence_threshold=0.9)
        resp = agent.answer("saldo")
        assert resp.confidence == pytest.approx(0.85)
        assert resp.escalated is True

    def test_threshold_boundary_at_or_above_passes(self, backend: FakeBackend) -> None:
        backend.response = "Seu saldo e R$ 100,00 disponivel."
        agent = ChatbotAgent(backend=backend, confidence_threshold=0.85)
        resp = agent.answer("saldo")
        assert resp.confidence == pytest.approx(0.85)
        assert resp.escalated is False

    def test_threshold_zero_never_escalates_on_short_answer(
        self, backend: FakeBackend
    ) -> None:
        backend.response = "x"
        agent = ChatbotAgent(backend=backend, confidence_threshold=0.0)
        resp = agent.answer("saldo")
        assert resp.escalated is False

    def test_threshold_one_always_escalates(self, backend: FakeBackend) -> None:
        backend.response = "Seu saldo e R$ 100,00 disponivel para saque."
        agent = ChatbotAgent(backend=backend, confidence_threshold=1.0)
        resp = agent.answer("saldo")
        assert resp.escalated is True

    def test_backend_exception_returns_safe_escalation(self) -> None:
        agent = ChatbotAgent(backend=FailingBackend())
        resp = agent.answer("Qual meu saldo?", session_id="sess-err", channel="app")
        assert resp.escalated is True
        assert resp.confidence == 0.0
        assert resp.intent == Intent.BALANCE
        assert resp.session_id == "sess-err"
        assert "atendente" in resp.answer.lower()
        assert "error" in resp.metadata
        assert resp.metadata["channel"] == "app"

    def test_channel_is_recorded_in_metadata(self, backend: FakeBackend) -> None:
        backend.response = "Seu saldo atual e R$ 1.000,00 disponivel."
        agent = ChatbotAgent(backend=backend, confidence_threshold=0.7)
        resp = agent.answer("saldo", channel="whatsapp")
        assert resp.metadata.get("channel") == "whatsapp"

    def test_system_prompt_is_prepended_to_backend_call(
        self, backend: FakeBackend
    ) -> None:
        backend.response = "Seu saldo atual e R$ 1.000,00 disponivel."
        agent = ChatbotAgent(backend=backend)
        agent.answer("saldo", channel="app")
        assert len(backend.calls) == 1
        prompt, _ = backend.calls[0]
        assert agent.system_prompt in prompt
        assert "Customer (app): saldo" in prompt

    def test_kwargs_are_forwarded_to_backend(self) -> None:
        backend = MagicMock()
        backend.complete.return_value = "Seu saldo e R$ 1.000,00 disponivel."
        agent = ChatbotAgent(backend=backend)
        agent.answer("saldo", temperature=0.2, max_tokens=64)
        _, kwargs = backend.complete.call_args
        assert kwargs == {"temperature": 0.2, "max_tokens": 64}

    def test_returns_chatresponse_instance(self, backend: FakeBackend) -> None:
        backend.response = "Seu saldo atual e R$ 1.000,00 disponivel."
        agent = ChatbotAgent(backend=backend)
        resp = agent.answer("saldo")
        assert isinstance(resp, ChatResponse)
        assert 0.0 <= resp.confidence <= 1.0

    def test_empty_query_classified_as_general_and_handled(
        self, backend: FakeBackend
    ) -> None:
        backend.response = "Como posso ajudar hoje? Estou a disposicao."
        agent = ChatbotAgent(backend=backend)
        resp = agent.answer("")
        assert resp.intent == Intent.GENERAL
        assert isinstance(resp, ChatResponse)
