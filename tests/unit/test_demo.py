# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for ``lub.connectors.bridge.demo``.

Exercises the demo entrypoints together with the full Bridge pipeline:

* ``DemoBackend`` keyword routing (the fake LLM used by the demo).
* End-to-end customer queries through ``ChatbotAgent`` with
  confidence-threshold gating and escalation behaviour.
* End-to-end payment parsing and validation through ``SmartPaymentAgent``
  including high-value warnings, per-rail limits, and the
  UncertaintyGuard confidence check.
* Call-center compliance scanning (PII / prohibited phrases) and
  suggestion generation with backend error fallback.
* Smoke tests for the demo ``demo_chatbot`` / ``demo_payments`` /
  ``demo_call_center`` / ``demo_api_info`` entrypoints via ``capsys``.

All LLM calls are routed through fake backends — no network is touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from lub.connectors.bridge import demo
from lub.connectors.bridge.agents.call_center import (
    CallCenterAgent,
    ComplianceSeverity,
)
from lub.connectors.bridge.agents.chatbot import ChatbotAgent, Intent
from lub.connectors.bridge.agents.smart_payments import (
    Currency,
    PaymentIntent,
    PaymentType,
    SmartPaymentAgent,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class FailingBackend:
    """Backend that always raises — simulates network/timeout failures."""

    error: Exception = RuntimeError("backend timeout")

    def complete(self, prompt: str, **kwargs: Any) -> str:
        raise self.error


@dataclass
class EmptyBackend:
    """Backend that returns an empty completion."""

    def complete(self, prompt: str, **kwargs: Any) -> str:  # noqa: ARG002
        return ""


@dataclass
class ShortBackend:
    """Backend whose answer is too short to pass the heuristic confidence."""

    def complete(self, prompt: str, **kwargs: Any) -> str:  # noqa: ARG002
        return "OK."


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def backend() -> demo.DemoBackend:
    return demo.DemoBackend()


@pytest.fixture
def chatbot(backend: demo.DemoBackend) -> ChatbotAgent:
    return ChatbotAgent(backend=backend, confidence_threshold=0.7)


@pytest.fixture
def payments(backend: demo.DemoBackend) -> SmartPaymentAgent:
    return SmartPaymentAgent(backend=backend, confidence_threshold=0.7)


@pytest.fixture
def call_center(backend: demo.DemoBackend) -> CallCenterAgent:
    return CallCenterAgent(backend=backend)


# ---------------------------------------------------------------------------
# DemoBackend (the fake LLM the demo wires into every agent)
# ---------------------------------------------------------------------------


class TestDemoBackend:
    def test_balance_keyword_routes_to_balance_response(
        self, backend: demo.DemoBackend
    ) -> None:
        assert backend.complete("Qual meu saldo?") == demo._RESPONSES["balance"]

    def test_pix_keyword_routes_to_pix_response(
        self, backend: demo.DemoBackend
    ) -> None:
        assert backend.complete("Quero fazer um pix") == demo._RESPONSES["pix"]

    def test_card_keyword_routes_to_card_response(
        self, backend: demo.DemoBackend
    ) -> None:
        assert backend.complete("Qual o valor da minha fatura?") == demo._RESPONSES["card"]

    def test_complaint_keyword_routes_to_complaint_response(
        self, backend: demo.DemoBackend
    ) -> None:
        out = backend.complete("Tenho um problema com cobranca")
        assert out == demo._RESPONSES["complaint"]

    def test_investment_keyword_routes_to_investment_response(
        self, backend: demo.DemoBackend
    ) -> None:
        assert backend.complete("Quero conhecer CDB") == demo._RESPONSES["investment"]

    def test_unknown_query_falls_back_to_general(
        self, backend: demo.DemoBackend
    ) -> None:
        assert backend.complete("asdfghjkl") == demo._RESPONSES["general"]

    def test_empty_query_returns_general_response(
        self, backend: demo.DemoBackend
    ) -> None:
        assert backend.complete("") == demo._RESPONSES["general"]

    def test_case_insensitive_keyword_match(
        self, backend: demo.DemoBackend
    ) -> None:
        assert backend.complete("SALDO") == backend.complete("saldo")

    def test_extra_kwargs_are_ignored(self, backend: demo.DemoBackend) -> None:
        out = backend.complete("Qual meu saldo?", temperature=0.7, max_tokens=100)
        assert out == demo._RESPONSES["balance"]


# ---------------------------------------------------------------------------
# Full chatbot pipeline: customer -> Bridge -> agent -> guard -> response
# ---------------------------------------------------------------------------


class TestChatbotPipeline:
    def test_balance_query_high_confidence_no_escalation(
        self, chatbot: ChatbotAgent
    ) -> None:
        response = chatbot.answer(
            "Qual meu saldo?", channel="whatsapp", session_id="s1"
        )
        assert response.intent is Intent.BALANCE
        assert response.escalated is False
        assert response.confidence >= 0.7
        assert response.answer == demo._RESPONSES["balance"]

    def test_pix_query_classified_as_pix(self, chatbot: ChatbotAgent) -> None:
        response = chatbot.answer("Quero fazer um PIX de 500 reais", channel="app")
        assert response.intent is Intent.PIX
        assert response.escalated is False

    def test_complaint_query_classified(self, chatbot: ChatbotAgent) -> None:
        response = chatbot.answer(
            "Tenho uma reclamacao sobre cobranca indevida", channel="web"
        )
        assert response.intent is Intent.COMPLAINT

    def test_nonsense_query_falls_back_to_general_intent(
        self, chatbot: ChatbotAgent
    ) -> None:
        response = chatbot.answer("asdfghjkl", channel="app")
        assert response.intent is Intent.GENERAL

    def test_session_id_propagates_to_response(
        self, chatbot: ChatbotAgent
    ) -> None:
        response = chatbot.answer("Qual meu saldo?", session_id="demo-001")
        assert response.session_id == "demo-001"

    def test_channel_recorded_in_metadata(self, chatbot: ChatbotAgent) -> None:
        response = chatbot.answer("Qual meu saldo?", channel="whatsapp")
        assert response.metadata.get("channel") == "whatsapp"

    def test_backend_exception_escalates_with_zero_confidence(self) -> None:
        agent = ChatbotAgent(backend=FailingBackend(), confidence_threshold=0.7)
        response = agent.answer("Qual meu saldo?", channel="app")
        assert response.escalated is True
        assert response.confidence == 0.0
        assert "error" in response.metadata

    def test_empty_backend_response_escalates(self) -> None:
        agent = ChatbotAgent(backend=EmptyBackend(), confidence_threshold=0.7)
        response = agent.answer("Qual meu saldo?", channel="app")
        assert response.escalated is True
        assert response.confidence < 0.7

    def test_threshold_above_max_heuristic_forces_escalation(
        self, backend: demo.DemoBackend
    ) -> None:
        agent = ChatbotAgent(backend=backend, confidence_threshold=0.99)
        response = agent.answer("Qual meu saldo?", channel="app")
        assert response.escalated is True
        # Original answer preserved for audit
        assert response.metadata.get("original_answer") == demo._RESPONSES["balance"]

    def test_low_threshold_accepts_short_responses(self) -> None:
        agent = ChatbotAgent(backend=ShortBackend(), confidence_threshold=0.05)
        response = agent.answer("Qual meu saldo?", channel="app")
        assert response.escalated is False

    def test_chatbot_calls_backend_with_system_prompt_and_query(self) -> None:
        mock_backend = MagicMock()
        mock_backend.complete.return_value = "Seu saldo e R$ 100,00."
        agent = ChatbotAgent(backend=mock_backend, confidence_threshold=0.7)
        agent.answer("Qual meu saldo?", channel="app", session_id="abc")

        mock_backend.complete.assert_called_once()
        prompt_arg = mock_backend.complete.call_args.args[0]
        assert "Qual meu saldo?" in prompt_arg
        assert "Banco Bradesco" in prompt_arg
        assert "Customer (app)" in prompt_arg

    def test_response_serializes_to_dict(self, chatbot: ChatbotAgent) -> None:
        response = chatbot.answer("Qual meu saldo?", session_id="s2")
        payload = response.to_dict()
        assert payload["intent"] == Intent.BALANCE.value
        assert payload["session_id"] == "s2"
        assert isinstance(payload["confidence"], float)


# ---------------------------------------------------------------------------
# Full payments pipeline: parse -> validate -> guard
# ---------------------------------------------------------------------------


class TestPaymentsPipeline:
    def test_pix_payment_parsed_correctly(
        self, payments: SmartPaymentAgent
    ) -> None:
        intent = payments.parse_payment("Pagar 150 reais pro Joao via PIX")
        assert intent.payment_type is PaymentType.PIX
        assert intent.amount == Decimal("150")
        assert intent.currency is Currency.BRL
        assert "joao" in intent.recipient.lower()

    def test_ted_payment_parsed_correctly(
        self, payments: SmartPaymentAgent
    ) -> None:
        intent = payments.parse_payment(
            "Transferir 50000 por TED pra conta da empresa"
        )
        assert intent.payment_type is PaymentType.TED
        assert intent.amount == Decimal("50000")

    def test_default_payment_type_is_pix(
        self, payments: SmartPaymentAgent
    ) -> None:
        intent = payments.parse_payment("Mandar 10 reais pra Maria")
        assert intent.payment_type is PaymentType.PIX

    def test_high_value_warning_emitted(self, payments: SmartPaymentAgent) -> None:
        intent = payments.parse_payment("Pagar 50000 via PIX pra Joao")
        result = payments.validate_payment(intent)
        assert any("alto valor" in w.lower() for w in result.warnings)

    def test_pix_over_limit_invalid(self, payments: SmartPaymentAgent) -> None:
        intent = payments.parse_payment("Pagar 200000 via PIX pra Joao")
        result = payments.validate_payment(intent)
        assert result.valid is False
        assert any(
            "excede" in e.lower() or "limite" in e.lower() for e in result.errors
        )

    def test_doc_over_cap_invalid(self, payments: SmartPaymentAgent) -> None:
        intent = PaymentIntent(
            recipient="Empresa LTDA",
            amount=Decimal("5000.00"),
            currency=Currency.BRL,
            payment_type=PaymentType.DOC,
            confidence=0.95,
        )
        result = payments.validate_payment(intent)
        assert result.valid is False
        assert any("DOC" in e for e in result.errors)

    def test_negative_amount_invalid(self, payments: SmartPaymentAgent) -> None:
        intent = PaymentIntent(
            recipient="Joao",
            amount=Decimal("-10"),
            currency=Currency.BRL,
            payment_type=PaymentType.PIX,
            confidence=0.95,
        )
        result = payments.validate_payment(intent)
        assert result.valid is False
        assert any("positivo" in e.lower() for e in result.errors)

    def test_zero_amount_invalid(self, payments: SmartPaymentAgent) -> None:
        intent = PaymentIntent(
            recipient="Joao",
            amount=Decimal("0"),
            currency=Currency.BRL,
            payment_type=PaymentType.PIX,
            confidence=0.95,
        )
        result = payments.validate_payment(intent)
        assert result.valid is False

    def test_missing_recipient_invalid(
        self, payments: SmartPaymentAgent
    ) -> None:
        intent = PaymentIntent(
            recipient="",
            amount=Decimal("100"),
            currency=Currency.BRL,
            payment_type=PaymentType.PIX,
            confidence=0.95,
        )
        result = payments.validate_payment(intent)
        assert result.valid is False
        assert any("destinatario" in e.lower() for e in result.errors)

    def test_low_confidence_intent_invalid(
        self, payments: SmartPaymentAgent
    ) -> None:
        intent = PaymentIntent(
            recipient="Joao",
            amount=Decimal("100"),
            currency=Currency.BRL,
            payment_type=PaymentType.PIX,
            confidence=0.3,
        )
        result = payments.validate_payment(intent)
        assert result.valid is False
        assert any("confianca" in e.lower() for e in result.errors)

    def test_valid_low_value_pix_passes(
        self, payments: SmartPaymentAgent
    ) -> None:
        intent = PaymentIntent(
            recipient="Maria",
            amount=Decimal("50"),
            currency=Currency.BRL,
            payment_type=PaymentType.PIX,
            confidence=0.95,
        )
        result = payments.validate_payment(intent)
        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []  # below high-value threshold

    def test_empty_text_yields_invalid_payment(
        self, backend: demo.DemoBackend
    ) -> None:
        agent = SmartPaymentAgent(backend=backend, confidence_threshold=0.7)
        intent = agent.parse_payment("")
        result = agent.validate_payment(intent)
        assert result.valid is False

    def test_brazilian_decimal_format_parsed(
        self, payments: SmartPaymentAgent
    ) -> None:
        intent = payments.parse_payment("Pagar R$ 1.250,75 via PIX pra Joao")
        assert intent.amount == Decimal("1250.75")


# ---------------------------------------------------------------------------
# Full call-center pipeline: compliance + suggestion + error fallback
# ---------------------------------------------------------------------------


class TestCallCenterPipeline:
    def test_cpf_in_transcript_flagged_critical(
        self, call_center: CallCenterAgent
    ) -> None:
        flags = call_center.flag_compliance(
            "Meu CPF e 123.456.789-00 e preciso de ajuda."
        )
        cpf_flags = [f for f in flags if "CPF" in f.rule]
        assert cpf_flags
        assert all(f.severity is ComplianceSeverity.CRITICAL for f in cpf_flags)

    def test_credit_card_in_transcript_flagged(
        self, call_center: CallCenterAgent
    ) -> None:
        flags = call_center.flag_compliance(
            "Anote meu cartao 1234567890123 para confirmacao."
        )
        assert any("CREDIT_CARD" in f.rule for f in flags)

    def test_email_in_transcript_flagged(
        self, call_center: CallCenterAgent
    ) -> None:
        flags = call_center.flag_compliance(
            "Meu email e cliente@exemplo.com, mande o boleto."
        )
        assert any("EMAIL" in f.rule for f in flags)

    def test_clean_transcript_yields_no_flags(
        self, call_center: CallCenterAgent
    ) -> None:
        flags = call_center.flag_compliance(
            "Bom dia, gostaria de ajuda com minha conta."
        )
        assert flags == []

    def test_prohibited_guarantee_phrase_flagged_high(
        self, call_center: CallCenterAgent
    ) -> None:
        flags = call_center.flag_compliance(
            "Este investimento oferece garantia de retorno todo mes."
        )
        guarantee = [f for f in flags if f.rule == "GUARANTEE_RETURN"]
        assert guarantee
        assert all(f.severity is ComplianceSeverity.HIGH for f in guarantee)

    def test_suggest_response_returns_text_within_bounds(
        self, call_center: CallCenterAgent
    ) -> None:
        suggestion = call_center.suggest_response(
            "Cliente: Tenho um problema com minha fatura de cartao."
        )
        assert suggestion.text
        assert 0.0 <= suggestion.confidence <= 1.0
        assert len(suggestion.alternatives) <= call_center.max_alternatives

    def test_suggest_response_detects_complaint_intent(
        self, call_center: CallCenterAgent
    ) -> None:
        suggestion = call_center.suggest_response(
            "Cliente: estou com um problema serio na conta."
        )
        assert suggestion.intent == "reclamacao"

    def test_suggest_response_backend_error_returns_safe_fallback(self) -> None:
        agent = CallCenterAgent(backend=FailingBackend())
        suggestion = agent.suggest_response("Cliente: problema na fatura.")
        assert suggestion.confidence == 0.0
        assert suggestion.text  # safe non-empty fallback
        assert suggestion.alternatives == []

    def test_summarize_history_empty_returns_default_message(
        self, call_center: CallCenterAgent
    ) -> None:
        summary = call_center.summarize_history([])
        assert "Nenhum historico" in summary

    def test_summarize_history_backend_failure_returns_safe_fallback(self) -> None:
        agent = CallCenterAgent(backend=FailingBackend())
        summary = agent.summarize_history(
            [{"date": "2026-01-01", "channel": "app", "summary": "Saldo consultado."}]
        )
        assert "1 interacoes" in summary


# ---------------------------------------------------------------------------
# Demo entrypoint smoke tests (functions that print to stdout)
# ---------------------------------------------------------------------------


class TestDemoEntrypoints:
    def test_demo_chatbot_runs_and_prints_confidences(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        demo.demo_chatbot()
        out = capsys.readouterr().out
        assert "Chatbot Demo" in out
        assert "Confidence" in out
        assert "Intent" in out

    def test_demo_payments_runs_and_prints_parsed_intents(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        demo.demo_payments()
        out = capsys.readouterr().out
        assert "Smart Payments Demo" in out
        assert "Confidence" in out
        assert "Valid" in out

    def test_demo_call_center_runs_and_emits_compliance(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        demo.demo_call_center()
        out = capsys.readouterr().out
        assert "Call Center Demo" in out
        # Transcript contains a CPF; compliance section must appear
        assert "Compliance" in out or "PII_EXPOSURE" in out

    def test_demo_api_info_lists_core_endpoints(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        demo.demo_api_info()
        out = capsys.readouterr().out
        assert "/query" in out
        assert "/health" in out
        assert "/metrics" in out
        assert "/agents" in out
