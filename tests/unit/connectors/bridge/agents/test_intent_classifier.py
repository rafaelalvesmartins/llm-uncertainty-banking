# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for :mod:`lub.connectors.bridge.agents.intent_classifier`.

The intent classifier is the *first* governance checkpoint on the
Bradesco Bridge: every customer message flows through it before being
routed to a downstream agent (chatbot, smart payments, call center).
These tests cover the full Bridge ingress path:

* keyword-baseline classification in PT-BR and EN;
* the dual-stage LLM fallback contract (low confidence -> ask LLM,
  high confidence -> answer directly);
* edge cases that surface at the Bridge perimeter -- empty input,
  whitespace-only queries, PII-bearing strings, mixed case;
* error handling for the LLM backend (timeout-style exceptions,
  unparseable replies) so the platform never blocks on a flaky LLM.

LLM calls are mocked via the in-module ``_FakeLLM`` test double so the
suite stays hermetic and deterministic -- a hard requirement for the
BCB 4893 audit-replay tooling that runs this suite in CI.
"""

from __future__ import annotations

from typing import Any

import pytest

from lub.connectors.bridge.agents.chatbot import Intent
from lub.connectors.bridge.agents.intent_classifier import (
    ClassificationMethod,
    IntentClassifier,
    IntentResult,
    Language,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeLLM:
    """Deterministic stand-in for :class:`LLMBackend`.

    Returns ``reply`` for every prompt and records the calls so tests
    can assert that the LLM fallback was (or was not) exercised.
    """

    def __init__(self, reply: str = "pix") -> None:
        self.reply = reply
        self.calls: list[str] = []

    def complete(self, prompt: str, **kwargs: Any) -> str:
        self.calls.append(prompt)
        return self.reply


class _BoomLLM:
    """LLM double that always raises -- exercises the error path."""

    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc or TimeoutError("backend timeout")
        self.calls: list[str] = []

    def complete(self, prompt: str, **kwargs: Any) -> str:
        self.calls.append(prompt)
        raise self.exc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def classifier() -> IntentClassifier:
    """A keyword-only classifier (no LLM wired)."""
    return IntentClassifier()


@pytest.fixture
def fake_llm() -> _FakeLLM:
    return _FakeLLM(reply="pix")


@pytest.fixture
def classifier_with_llm(fake_llm: _FakeLLM) -> IntentClassifier:
    """Classifier with a deterministic fake LLM and default thresholds."""
    return IntentClassifier(llm_backend=fake_llm)


# ---------------------------------------------------------------------------
# Keyword baseline: PT-BR
# ---------------------------------------------------------------------------


class TestKeywordBaselinePortuguese:
    """Bridge ingress: PT-BR queries through the keyword stage."""

    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("Qual e o meu saldo?", Intent.BALANCE),
            ("Quero fazer uma transferencia", Intent.TRANSFER),
            ("Preciso fazer um pix urgente", Intent.PIX),
            ("Solicitar emprestimo consignado", Intent.LOAN),
            ("Bloquear cartao", Intent.CARD),
            ("Quero investir em tesouro direto", Intent.INVESTMENT),
            ("Tenho uma reclamacao a fazer", Intent.COMPLAINT),
        ],
    )
    def test_pt_br_routes_to_expected_intent(
        self,
        classifier: IntentClassifier,
        query: str,
        expected: Intent,
    ) -> None:
        result = classifier.classify(query, language=Language.PT_BR)
        assert result.intent is expected
        assert 0.0 < result.confidence <= 1.0
        assert result.method is ClassificationMethod.KEYWORD
        assert result.language is Language.PT_BR

    def test_pt_br_matched_keywords_recorded(self, classifier: IntentClassifier) -> None:
        result = classifier.classify("Quero ver meu saldo extrato")
        assert result.intent is Intent.BALANCE
        matched = result.metadata["matched_keywords"]
        assert "saldo" in matched
        assert "extrato" in matched

    def test_longer_keyword_outscores_shorter(self, classifier: IntentClassifier) -> None:
        # "chave pix" (9 chars) should outweigh a bare "pix" (3 chars).
        result = classifier.classify("Minha chave pix esta correta?")
        assert result.intent is Intent.PIX
        # confidence is share of total score; the longer hit dominates.
        assert result.confidence > 0.5


# ---------------------------------------------------------------------------
# Keyword baseline: English
# ---------------------------------------------------------------------------


class TestKeywordBaselineEnglish:
    """Bridge ingress: EN queries through the keyword stage."""

    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("What is my account balance?", Intent.BALANCE),
            ("I want to transfer money", Intent.TRANSFER),
            ("How do I send pix?", Intent.PIX),
            ("Apply for a loan", Intent.LOAN),
            ("Block my credit card", Intent.CARD),
            ("Invest in treasury bonds", Intent.INVESTMENT),
            ("I have a complaint", Intent.COMPLAINT),
        ],
    )
    def test_en_routes_to_expected_intent(
        self,
        classifier: IntentClassifier,
        query: str,
        expected: Intent,
    ) -> None:
        result = classifier.classify(query, language=Language.EN)
        assert result.intent is expected
        assert result.confidence > 0.0
        assert result.language is Language.EN

    def test_en_accepts_string_language_alias(self, classifier: IntentClassifier) -> None:
        result = classifier.classify("check my balance", language="en")
        assert result.intent is Intent.BALANCE
        assert result.language is Language.EN


# ---------------------------------------------------------------------------
# Confidence / ranking semantics
# ---------------------------------------------------------------------------


class TestConfidenceAndRanking:
    """Confidence is the audit-trail field downstream agents trust."""

    def test_confidence_is_normalized_share(self, classifier: IntentClassifier) -> None:
        result = classifier.classify("saldo")
        # only one keyword hits exactly one intent -> share == 1.0
        assert result.intent is Intent.BALANCE
        assert result.confidence == pytest.approx(1.0)

    def test_alternatives_ranked_descending(self, classifier: IntentClassifier) -> None:
        # A query that hits two distinct intents.
        result = classifier.classify("pix e transferencia")
        scores = [score for _, score in result.alternatives]
        assert scores == sorted(scores, reverse=True)

    def test_alternatives_capped_at_three(self, classifier: IntentClassifier) -> None:
        # No matter how many intents fire we never expose more than 3.
        # Hit five different intents at once.
        result = classifier.classify(
            "saldo transferencia pix emprestimo cartao",
        )
        assert len(result.alternatives) <= 3
        for _, score in result.alternatives:
            assert score > 0


# ---------------------------------------------------------------------------
# Edge cases at the Bridge perimeter
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Inputs the customer-facing API will eventually receive."""

    def test_empty_query_returns_general_default(self, classifier: IntentClassifier) -> None:
        result = classifier.classify("")
        assert result.intent is Intent.GENERAL
        assert result.confidence == 0.0
        assert result.method is ClassificationMethod.DEFAULT
        assert result.alternatives == ()
        assert result.metadata["reason"] == "empty_query"

    def test_whitespace_query_returns_general_default(
        self, classifier: IntentClassifier
    ) -> None:
        result = classifier.classify("   \n\t  ")
        assert result.intent is Intent.GENERAL
        assert result.method is ClassificationMethod.DEFAULT

    def test_no_keyword_match_returns_general(self, classifier: IntentClassifier) -> None:
        result = classifier.classify("ola tudo bem com voce hoje?")
        assert result.intent is Intent.GENERAL
        assert result.confidence == 0.0
        assert result.method is ClassificationMethod.DEFAULT
        assert result.metadata["matched_keywords"] == []

    def test_mixed_case_is_normalized(self, classifier: IntentClassifier) -> None:
        result = classifier.classify("QUERO VER MEU SALDO")
        assert result.intent is Intent.BALANCE

    def test_pii_like_strings_do_not_crash(self, classifier: IntentClassifier) -> None:
        # Free text with a CPF, an email, and a card-shaped number must
        # not raise -- the classifier's job is to tag, not to redact.
        query = "fazer pix para joao@example.com cpf 123.456.789-00"
        result = classifier.classify(query)
        assert result.intent is Intent.PIX
        # Metadata is never used for routing, but it must be JSON-safe.
        assert isinstance(result.to_dict(), dict)

    def test_invalid_amount_text_still_classifies_intent(
        self, classifier: IntentClassifier
    ) -> None:
        # Numbers / malformed amounts must not break intent tagging.
        result = classifier.classify("transferir R$ -9999,99 para ninguem")
        assert result.intent is Intent.TRANSFER


# ---------------------------------------------------------------------------
# Language resolution
# ---------------------------------------------------------------------------


class TestLanguageResolution:
    def test_none_language_falls_back_to_default(self) -> None:
        clf = IntentClassifier(default_language=Language.EN)
        result = clf.classify("check balance", language=None)
        assert result.language is Language.EN

    def test_unknown_string_language_warns_and_uses_default(
        self,
        classifier: IntentClassifier,
    ) -> None:
        # Unknown locale -- classifier must not raise, must fall back.
        result = classifier.classify("saldo", language="fr-FR")
        assert result.language is classifier.default_language
        assert result.intent is Intent.BALANCE

    def test_enum_language_is_accepted(self, classifier: IntentClassifier) -> None:
        result = classifier.classify("balance", language=Language.EN)
        assert result.language is Language.EN


# ---------------------------------------------------------------------------
# LLM fallback contract
# ---------------------------------------------------------------------------


class TestLLMFallback:
    """When the keyword baseline is uncertain the LLM is consulted."""

    def test_high_confidence_skips_llm(self, fake_llm: _FakeLLM) -> None:
        clf = IntentClassifier(llm_backend=fake_llm, llm_fallback_threshold=0.5)
        result = clf.classify("saldo")  # unambiguous -> confidence 1.0
        assert result.method is ClassificationMethod.KEYWORD
        assert fake_llm.calls == []

    def test_low_confidence_triggers_llm(self) -> None:
        fake = _FakeLLM(reply="pix")
        # Force the LLM path: high threshold so even confident hits go to LLM.
        clf = IntentClassifier(llm_backend=fake, llm_fallback_threshold=1.01)
        result = clf.classify("fazer pix")
        assert result.method is ClassificationMethod.LLM_FALLBACK
        assert result.intent is Intent.PIX
        assert result.confidence == pytest.approx(0.9)
        assert len(fake.calls) == 1

    def test_ambiguity_margin_triggers_llm_when_top_intents_tie(self) -> None:
        # Two intents tie -> margin == 0 -> below default 0.15 margin.
        fake = _FakeLLM(reply="pix")
        clf = IntentClassifier(llm_backend=fake)
        result = clf.classify("pix ted")  # 3-char hit for both
        assert result.method is ClassificationMethod.LLM_FALLBACK
        assert fake.calls, "LLM should be consulted on ambiguous queries"

    def test_no_llm_backend_means_keyword_only(self) -> None:
        clf = IntentClassifier(llm_backend=None, llm_fallback_threshold=0.99)
        result = clf.classify("pix ted")  # ambiguous, but no LLM available
        assert result.method is ClassificationMethod.KEYWORD

    def test_empty_query_never_calls_llm(self) -> None:
        fake = _FakeLLM(reply="pix")
        clf = IntentClassifier(llm_backend=fake)
        clf.classify("")
        assert fake.calls == []

    def test_no_match_never_calls_llm(self) -> None:
        # If keyword stage produces zero score, the LLM is *not* asked --
        # the classifier returns GENERAL as a safe default.
        fake = _FakeLLM(reply="pix")
        clf = IntentClassifier(llm_backend=fake)
        result = clf.classify("ola tudo bem")
        assert fake.calls == []
        assert result.intent is Intent.GENERAL


# ---------------------------------------------------------------------------
# LLM error handling
# ---------------------------------------------------------------------------


class TestLLMErrorHandling:
    """The Bridge must never block on a flaky LLM."""

    def test_llm_timeout_falls_back_to_keyword(self) -> None:
        boom = _BoomLLM(TimeoutError("backend timeout"))
        clf = IntentClassifier(llm_backend=boom, llm_fallback_threshold=1.01)
        result = clf.classify("pix")
        assert result.method is ClassificationMethod.KEYWORD
        assert result.intent is Intent.PIX
        assert boom.calls, "LLM was called but failed -- expected fallback path"

    def test_llm_generic_exception_falls_back_to_keyword(self) -> None:
        boom = _BoomLLM(RuntimeError("backend exploded"))
        clf = IntentClassifier(llm_backend=boom, llm_fallback_threshold=1.01)
        result = clf.classify("saldo")
        assert result.method is ClassificationMethod.KEYWORD
        assert result.intent is Intent.BALANCE

    def test_llm_unparseable_reply_falls_back_to_keyword(self) -> None:
        fake = _FakeLLM(reply="???not a valid intent???")
        clf = IntentClassifier(llm_backend=fake, llm_fallback_threshold=1.01)
        result = clf.classify("pix")
        assert result.method is ClassificationMethod.KEYWORD
        assert result.intent is Intent.PIX

    def test_llm_empty_reply_falls_back_to_keyword(self) -> None:
        fake = _FakeLLM(reply="")
        clf = IntentClassifier(llm_backend=fake, llm_fallback_threshold=1.01)
        result = clf.classify("pix")
        assert result.method is ClassificationMethod.KEYWORD
        assert result.intent is Intent.PIX

    def test_llm_reply_with_punctuation_is_parsed(self) -> None:
        # LLMs sometimes wrap the answer: '"pix".'
        fake = _FakeLLM(reply='"pix".')
        clf = IntentClassifier(llm_backend=fake, llm_fallback_threshold=1.01)
        result = clf.classify("pagar com qr code")
        assert result.method is ClassificationMethod.LLM_FALLBACK
        assert result.intent is Intent.PIX


# ---------------------------------------------------------------------------
# IntentResult serialization
# ---------------------------------------------------------------------------


class TestIntentResultSerialization:
    """The audit trail persists IntentResult.to_dict() verbatim."""

    def test_to_dict_round_trips_core_fields(self, classifier: IntentClassifier) -> None:
        result = classifier.classify("Quero ver meu saldo")
        payload = result.to_dict()
        assert payload["intent"] == Intent.BALANCE.value
        assert payload["language"] == Language.PT_BR.value
        assert payload["method"] == ClassificationMethod.KEYWORD.value
        assert 0.0 < payload["confidence"] <= 1.0
        assert isinstance(payload["alternatives"], list)
        assert isinstance(payload["metadata"], dict)

    def test_alternatives_are_serialized_as_dicts(
        self,
        classifier: IntentClassifier,
    ) -> None:
        result = classifier.classify("saldo transferencia pix")
        payload = result.to_dict()
        for alt in payload["alternatives"]:
            assert set(alt.keys()) == {"intent", "score"}
            assert isinstance(alt["intent"], str)
            assert isinstance(alt["score"], float)

    def test_default_construction_is_safe(self) -> None:
        # The dataclass should be constructable with only the required
        # fields -- exercised by callers that build a synthetic result.
        result = IntentResult(intent=Intent.GENERAL, confidence=0.0)
        assert result.language is Language.PT_BR
        assert result.method is ClassificationMethod.KEYWORD
        assert result.alternatives == ()
        assert result.metadata == {}


# ---------------------------------------------------------------------------
# Full Bridge pipeline -- threshold contract
# ---------------------------------------------------------------------------


class TestBridgeThresholdContract:
    """Confidence drives the downstream escalation decision on the Bridge.

    The classifier itself does not escalate -- it produces the score
    that :class:`~lub.guard.UncertaintyGuard` uses. These tests pin the
    score semantics so the guard's threshold check stays meaningful.
    """

    def test_unambiguous_query_clears_typical_guard_threshold(
        self,
        classifier: IntentClassifier,
    ) -> None:
        # A typical production threshold is 0.75; an unambiguous PT-BR
        # query must comfortably exceed it.
        result = classifier.classify("Qual e o meu saldo da conta corrente?")
        assert result.confidence >= 0.75
        assert result.intent is Intent.BALANCE

    def test_ambiguous_query_keyword_only_falls_below_guard_threshold(
        self,
        classifier: IntentClassifier,
    ) -> None:
        # Two equally-strong hits -> confidence ~= 0.5 -> guard escalates.
        result = classifier.classify("pix ted")
        assert result.confidence < 0.75

    def test_no_signal_query_routes_to_general_for_human(
        self,
        classifier: IntentClassifier,
    ) -> None:
        # Zero confidence + GENERAL intent is the "send to human" signal.
        result = classifier.classify("ola, bom dia")
        assert result.intent is Intent.GENERAL
        assert result.confidence == 0.0
