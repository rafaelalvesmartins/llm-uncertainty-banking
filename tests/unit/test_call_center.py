# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for lub.agents.call_center.

Exercises the public surface of :class:`CallCenterAgent` plus the value
objects (:class:`Suggestion`, :class:`ComplianceFlag`, :class:`ComplianceSeverity`).
External LLM calls are mocked through a small in-memory backend; no
network or filesystem access is required.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from lub.connectors.bridge.agents.call_center import (
    CallCenterAgent,
    ComplianceFlag,
    ComplianceSeverity,
    Suggestion,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeBackend:
    """Deterministic backend that returns a canned completion."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[str] = []

    def complete(self, prompt: str, **kwargs: Any) -> str:
        self.calls.append(prompt)
        return self.response


class _FailingBackend:
    """Backend whose ``complete`` always raises."""

    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc or RuntimeError("backend down")
        self.calls: list[str] = []

    def complete(self, prompt: str, **kwargs: Any) -> str:
        self.calls.append(prompt)
        raise self.exc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_backend() -> _FakeBackend:
    return _FakeBackend(
        response=(
            "Posso ajudar com o cancelamento do seu cartao agora.\n"
            "ALT: Vou iniciar o cancelamento do cartao para voce.\n"
            "ALT: Confirmo o cancelamento do cartao em alguns minutos."
        )
    )


@pytest.fixture
def agent(fake_backend: _FakeBackend) -> CallCenterAgent:
    return CallCenterAgent(backend=fake_backend)


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class TestComplianceSeverity:
    def test_values(self) -> None:
        assert ComplianceSeverity.LOW.value == "low"
        assert ComplianceSeverity.MEDIUM.value == "medium"
        assert ComplianceSeverity.HIGH.value == "high"
        assert ComplianceSeverity.CRITICAL.value == "critical"

    def test_string_enum(self) -> None:
        # StrEnum members are strings.
        assert ComplianceSeverity.HIGH == "high"


class TestComplianceFlag:
    def test_construction(self) -> None:
        flag = ComplianceFlag(
            rule="PII_EXPOSURE_CPF",
            severity=ComplianceSeverity.CRITICAL,
            excerpt="123.456.789-00",
            recommendation="Mask CPF.",
        )
        assert flag.rule == "PII_EXPOSURE_CPF"
        assert flag.severity is ComplianceSeverity.CRITICAL
        assert flag.excerpt == "123.456.789-00"
        assert flag.recommendation == "Mask CPF."

    def test_frozen(self) -> None:
        flag = ComplianceFlag(
            rule="X",
            severity=ComplianceSeverity.LOW,
            excerpt="e",
            recommendation="r",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            flag.rule = "Y"  # type: ignore[misc]

    def test_asdict_roundtrip(self) -> None:
        flag = ComplianceFlag(
            rule="X",
            severity=ComplianceSeverity.MEDIUM,
            excerpt="e",
            recommendation="r",
        )
        data = dataclasses.asdict(flag)
        assert data["rule"] == "X"
        assert data["severity"] == ComplianceSeverity.MEDIUM  # StrEnum preserved
        rebuilt = ComplianceFlag(**data)
        assert rebuilt == flag


class TestSuggestion:
    def test_defaults(self) -> None:
        s = Suggestion(text="ok", confidence=0.9, intent="geral")
        assert s.alternatives == []

    def test_frozen(self) -> None:
        s = Suggestion(text="ok", confidence=0.9, intent="geral")
        with pytest.raises(dataclasses.FrozenInstanceError):
            s.confidence = 0.0  # type: ignore[misc]

    def test_asdict_roundtrip(self) -> None:
        s = Suggestion(text="ok", confidence=0.5, intent="cartao", alternatives=["a"])
        data = dataclasses.asdict(s)
        rebuilt = Suggestion(**data)
        assert rebuilt == s


# ---------------------------------------------------------------------------
# suggest_response
# ---------------------------------------------------------------------------


class TestSuggestResponse:
    def test_happy_path_parses_main_and_alternatives(
        self, agent: CallCenterAgent, fake_backend: _FakeBackend
    ) -> None:
        suggestion = agent.suggest_response("Cliente: quero cancelar meu cartao.")
        assert isinstance(suggestion, Suggestion)
        assert "cancelamento" in suggestion.text.lower()
        assert suggestion.intent == "cancelamento"
        assert len(suggestion.alternatives) == 2  # capped by max_alternatives
        assert all("ALT:" not in alt for alt in suggestion.alternatives)
        assert fake_backend.calls, "backend should be invoked"

    def test_confidence_in_unit_interval(self, agent: CallCenterAgent) -> None:
        suggestion = agent.suggest_response("Cliente: quero cancelar.")
        assert 0.0 <= suggestion.confidence <= 1.0

    def test_backend_failure_returns_safe_fallback(self) -> None:
        agent = CallCenterAgent(backend=_FailingBackend())
        suggestion = agent.suggest_response("Cliente: estou com problema.")
        assert suggestion.confidence == 0.0
        assert suggestion.intent == "reclamacao"
        assert suggestion.text  # non-empty fallback message
        assert suggestion.alternatives == []

    def test_empty_completion_yields_low_confidence(self) -> None:
        agent = CallCenterAgent(backend=_FakeBackend(response="   "))
        suggestion = agent.suggest_response("Cliente: pix nao caiu.")
        # Heuristic: empty / too-short answer → 0.1, which is below threshold.
        assert suggestion.confidence == pytest.approx(0.1)
        assert suggestion.confidence < agent.confidence_threshold

    def test_hedging_language_lowers_confidence(self) -> None:
        agent = CallCenterAgent(
            backend=_FakeBackend(response="Talvez eu possa ajudar com isso agora.")
        )
        suggestion = agent.suggest_response("Cliente: quero saldo da conta.")
        assert suggestion.confidence == pytest.approx(0.35)

    def test_max_alternatives_respected(self, fake_backend: _FakeBackend) -> None:
        agent = CallCenterAgent(backend=fake_backend, max_alternatives=1)
        suggestion = agent.suggest_response("Cliente: cancelar cartao.")
        assert len(suggestion.alternatives) <= 1


# ---------------------------------------------------------------------------
# summarize_history
# ---------------------------------------------------------------------------


class TestSummarizeHistory:
    def test_empty_history_short_circuits(self, agent: CallCenterAgent) -> None:
        summary = agent.summarize_history([])
        assert isinstance(summary, str)
        assert "Nenhum historico" in summary

    def test_empty_history_does_not_call_backend(
        self, agent: CallCenterAgent, fake_backend: _FakeBackend
    ) -> None:
        agent.summarize_history([])
        assert fake_backend.calls == []

    def test_with_entries_invokes_backend(
        self, agent: CallCenterAgent, fake_backend: _FakeBackend
    ) -> None:
        entries = [
            {"date": "2026-01-10", "channel": "phone", "summary": "Reclamacao de fatura."},
            {"date": "2026-02-02", "channel": "chat", "summary": "Solicitou aumento de limite."},
        ]
        result = agent.summarize_history(entries)
        assert isinstance(result, str)
        assert len(fake_backend.calls) == 1
        prompt = fake_backend.calls[0]
        assert "2026-01-10" in prompt
        assert "Reclamacao de fatura" in prompt

    def test_backend_failure_returns_count_fallback(self) -> None:
        agent = CallCenterAgent(backend=_FailingBackend())
        entries = [{"date": "x", "channel": "y", "summary": "z"}] * 3
        result = agent.summarize_history(entries)
        assert "3" in result
        assert "indisponivel" in result.lower() or "indispon" in result.lower()

    def test_missing_keys_use_defaults(
        self, agent: CallCenterAgent, fake_backend: _FakeBackend
    ) -> None:
        agent.summarize_history([{}])
        prompt = fake_backend.calls[0]
        assert "N/A" in prompt


# ---------------------------------------------------------------------------
# flag_compliance
# ---------------------------------------------------------------------------


class TestFlagCompliance:
    def test_clean_transcript_returns_empty_list(self, agent: CallCenterAgent) -> None:
        flags = agent.flag_compliance("Cliente: bom dia, gostaria de saber o saldo.")
        assert flags == []

    def test_detects_cpf(self, agent: CallCenterAgent) -> None:
        flags = agent.flag_compliance("Agente: seu CPF e 123.456.789-00 certo?")
        cpf_flags = [f for f in flags if f.rule == "PII_EXPOSURE_CPF"]
        assert len(cpf_flags) == 1
        assert cpf_flags[0].severity is ComplianceSeverity.CRITICAL
        assert "123.456.789-00" in cpf_flags[0].excerpt

    def test_detects_email(self, agent: CallCenterAgent) -> None:
        flags = agent.flag_compliance("Envie para cliente@example.com por favor.")
        email_flags = [f for f in flags if f.rule == "PII_EXPOSURE_EMAIL"]
        assert len(email_flags) == 1
        assert email_flags[0].severity is ComplianceSeverity.CRITICAL

    def test_detects_prohibited_phrase(self, agent: CallCenterAgent) -> None:
        flags = agent.flag_compliance(
            "Agente: este fundo oferece garantia de retorno acima do CDI."
        )
        rule_flags = [f for f in flags if f.rule == "GUARANTEE_RETURN"]
        assert len(rule_flags) == 1
        assert rule_flags[0].severity is ComplianceSeverity.HIGH
        assert "garantia de retorno" in rule_flags[0].excerpt.lower()

    def test_detects_multiple_risks(self, agent: CallCenterAgent) -> None:
        text = (
            "Agente: cliente CPF 123.456.789-00, "
            "este produto tem lucro garantido todo mes."
        )
        flags = agent.flag_compliance(text)
        rules = {f.rule for f in flags}
        assert "PII_EXPOSURE_CPF" in rules
        assert "GUARANTEE_PROFIT" in rules

    def test_does_not_call_backend(
        self, agent: CallCenterAgent, fake_backend: _FakeBackend
    ) -> None:
        agent.flag_compliance("Agente: seu CPF e 123.456.789-00.")
        assert fake_backend.calls == []

    def test_prohibited_phrase_excerpt_bounded(self, agent: CallCenterAgent) -> None:
        text = "x" * 500 + " garantia de retorno " + "y" * 500
        flags = agent.flag_compliance(text)
        assert flags
        # Excerpt should be a small window, not the full transcript.
        assert all(len(f.excerpt) < 200 for f in flags if f.rule == "GUARANTEE_RETURN")


# ---------------------------------------------------------------------------
# Intent + confidence helpers
# ---------------------------------------------------------------------------


class TestDetectIntent:
    @pytest.mark.parametrize(
        "transcript,expected",
        [
            ("Quero cancelar minha conta", "cancelamento"),
            ("Tenho uma reclamacao sobre o app", "reclamacao"),
            ("Qual e o saldo da conta?", "financeiro"),
            ("Meu cartao foi bloqueado", "cartao"),
            ("Quero investir em CDB", "investimento"),
            ("Preciso de um emprestimo", "emprestimo"),
            ("Bom dia, tudo bem?", "geral"),
        ],
    )
    def test_intent_routing(
        self, agent: CallCenterAgent, transcript: str, expected: str
    ) -> None:
        assert agent._detect_intent(transcript) == expected

    def test_intent_is_case_insensitive(self, agent: CallCenterAgent) -> None:
        assert agent._detect_intent("QUERO CANCELAR") == "cancelamento"


class TestEstimateConfidence:
    def test_empty_answer(self, agent: CallCenterAgent) -> None:
        assert agent._estimate_confidence("", "geral") == pytest.approx(0.1)

    def test_too_short_answer(self, agent: CallCenterAgent) -> None:
        assert agent._estimate_confidence("ok", "cartao") == pytest.approx(0.1)

    def test_hedging_answer(self, agent: CallCenterAgent) -> None:
        c = agent._estimate_confidence(
            "Talvez eu possa ajudar com isso, nao tenho certeza.", "cartao"
        )
        assert c == pytest.approx(0.35)

    def test_general_intent(self, agent: CallCenterAgent) -> None:
        c = agent._estimate_confidence(
            "Posso transferir para o setor responsavel.", "geral"
        )
        assert c == pytest.approx(0.7)

    def test_specific_intent(self, agent: CallCenterAgent) -> None:
        c = agent._estimate_confidence(
            "Posso iniciar o cancelamento do seu cartao agora.", "cartao"
        )
        assert c == pytest.approx(0.85)

    @pytest.mark.parametrize(
        "answer,intent",
        [
            ("", "geral"),
            ("Talvez sim, talvez nao, nao sei dizer.", "cartao"),
            ("Posso transferir para o setor responsavel.", "geral"),
            ("Vou iniciar o cancelamento agora mesmo.", "cancelamento"),
        ],
    )
    def test_confidence_in_unit_interval(
        self, agent: CallCenterAgent, answer: str, intent: str
    ) -> None:
        c = agent._estimate_confidence(answer, intent)
        assert 0.0 <= c <= 1.0


# ---------------------------------------------------------------------------
# Parsing helper
# ---------------------------------------------------------------------------


class TestParseSuggestion:
    def test_main_and_alternatives(self, agent: CallCenterAgent) -> None:
        raw = "Main reply.\nALT: First alt.\nALT: Second alt."
        main, alts = agent._parse_suggestion(raw)
        assert main == "Main reply."
        assert alts == ["First alt.", "Second alt."]

    def test_no_alternatives(self, agent: CallCenterAgent) -> None:
        main, alts = agent._parse_suggestion("Just one line.")
        assert main == "Just one line."
        assert alts == []

    def test_only_alternatives_falls_back_to_raw(self, agent: CallCenterAgent) -> None:
        raw = "ALT: only this."
        main, alts = agent._parse_suggestion(raw)
        # No main lines → falls back to stripped raw.
        assert main == raw
        assert alts == ["only this."]

    def test_case_insensitive_alt_prefix(self, agent: CallCenterAgent) -> None:
        raw = "Main.\nalt: lowercase still counts."
        main, alts = agent._parse_suggestion(raw)
        assert main == "Main."
        assert alts == ["lowercase still counts."]
