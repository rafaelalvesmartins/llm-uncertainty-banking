# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""NLU intent classifier for the Bradesco Bridge banking platform.

Classifies customer queries into banking intents with calibrated
confidence scores. The classifier is **dual-stage**:

1. **Keyword baseline** -- deterministic, language-aware lexical scoring.
   Fast, auditable, and works offline. Produces a confidence score in
   ``[0, 1]`` together with ranked alternative intents.
2. **LLM fallback** *(optional)* -- when the baseline confidence is
   below ``llm_fallback_threshold`` or the top two intents are too close
   to call, an LLM backend is asked to disambiguate. The LLM is only
   used for ambiguous queries, keeping latency and cost predictable.

Supports Brazilian Portuguese (``pt-BR``) and English (``en``). The
keyword tables for both languages are kept in this module so that the
classifier is fully self-contained and does not require any external
NLU service to start serving traffic.

**Banking / compliance relevance.** Intent classification is the first
governance checkpoint on the Bridge: every customer message is tagged
with an intent label and a confidence number that downstream agents and
the :class:`~lub.guard.UncertaintyGuard` use to decide whether to
answer, escalate, or route to a specialized agent (chatbot, call center
assist, smart payments). The confidence score feeds the BCB 4893 audit
trail (every routed query carries its classifier confidence and the
runner-up intents) and the SR 11-7 model-risk metrics around accuracy
and resolution rate that Bradesco publishes (95% accuracy, 90%
retention, 40% reduction in call handling time).
"""

# bridge-governance: upstream -- customer text is governed by BridgePlatform.process_query (bridge-ui/backend/server.py: _GOVERNOR.govern at the BFF). Agent sees masked text. See DATA_GOVERNANCE.md section 4a.
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

import structlog

from lub.connectors.bridge.agents.chatbot import Intent

_LOG = structlog.get_logger("lub.agents.intent_classifier")


class Language(StrEnum):
    """Supported NLU languages."""

    PT_BR = "pt-BR"
    EN = "en"


class ClassificationMethod(StrEnum):
    """How a given classification was produced.

    Recorded on every :class:`IntentResult` so the audit trail can show
    *why* a particular intent was chosen -- a regulator requirement
    under BCB 4893 and SR 11-7 model-risk reporting.
    """

    KEYWORD = "keyword"
    LLM_FALLBACK = "llm_fallback"
    DEFAULT = "default"


# ---------------------------------------------------------------------------
# Language-specific keyword tables.
#
# Each entry maps an :class:`Intent` to a list of trigger keywords.
# Tables are kept small and conservative -- a missed keyword is safer
# than a false positive on a financial intent (a wrong "pix" tag could
# route a complaint to a payment agent and leak PII).
# ---------------------------------------------------------------------------

_PT_KEYWORDS: dict[Intent, tuple[str, ...]] = {
    Intent.BALANCE: (
        "saldo",
        "extrato",
        "quanto tenho",
        "quanto eu tenho",
        "consultar saldo",
        "ver saldo",
    ),
    Intent.TRANSFER: (
        "transferir",
        "transferencia",
        "enviar dinheiro",
        "ted",
        "doc",
        "mandar dinheiro",
    ),
    Intent.PIX: (
        "pix",
        "chave pix",
        "fazer pix",
        "enviar pix",
        "pagar pix",
        "qr code",
    ),
    Intent.LOAN: (
        "emprestimo",
        "credito",
        "financiamento",
        "consignado",
        "pegar emprestado",
        "parcelar",
    ),
    Intent.CARD: (
        "cartao",
        "fatura",
        "limite",
        "credito do cartao",
        "bloquear cartao",
        "segunda via",
    ),
    Intent.INVESTMENT: (
        "investimento",
        "investir",
        "cdb",
        "tesouro",
        "tesouro direto",
        "fundo",
        "renda fixa",
        "aplicacao",
    ),
    Intent.COMPLAINT: (
        "reclamacao",
        "reclamar",
        "problema",
        "nao funciona",
        "erro",
        "ouvidoria",
        "insatisfeito",
    ),
}

_EN_KEYWORDS: dict[Intent, tuple[str, ...]] = {
    Intent.BALANCE: (
        "balance",
        "statement",
        "how much do i have",
        "account balance",
        "check balance",
    ),
    Intent.TRANSFER: (
        "transfer",
        "send money",
        "wire",
        "ted",
        "doc",
        "move money",
    ),
    Intent.PIX: (
        "pix",
        "pix key",
        "send pix",
        "make a pix",
        "qr code",
    ),
    Intent.LOAN: (
        "loan",
        "credit line",
        "financing",
        "borrow",
        "installment",
        "mortgage",
    ),
    Intent.CARD: (
        "card",
        "credit card",
        "debit card",
        "bill",
        "limit",
        "block card",
        "new card",
    ),
    Intent.INVESTMENT: (
        "investment",
        "invest",
        "cd",
        "bond",
        "treasury",
        "fund",
        "fixed income",
        "portfolio",
    ),
    Intent.COMPLAINT: (
        "complaint",
        "complain",
        "problem",
        "not working",
        "error",
        "issue",
        "unhappy",
        "dissatisfied",
    ),
}

_KEYWORDS_BY_LANGUAGE: dict[Language, dict[Intent, tuple[str, ...]]] = {
    Language.PT_BR: _PT_KEYWORDS,
    Language.EN: _EN_KEYWORDS,
}


@dataclass(frozen=True)
class IntentResult:
    """Outcome of an intent classification call.

    Attributes:
        intent: Top-ranked banking intent.
        confidence: Calibrated confidence in ``[0, 1]``. Computed as the
            top score normalized by the sum of all positive scores; a
            single-keyword unambiguous hit yields ``1.0``, while a query
            with no keyword hits yields ``0.0`` and resolves to
            :attr:`Intent.GENERAL`.
        alternatives: Up to three runner-up ``(intent, score)`` pairs,
            ordered by descending score. Useful for the audit trail and
            for the orchestrator's fallback policy.
        language: Language detected / supplied for this query.
        method: How the result was produced -- keyword scoring, LLM
            disambiguation, or the default ``GENERAL`` fallback.
        metadata: Free-form diagnostics (matched keywords, raw LLM
            response, latency). Never used for routing logic.
    """

    intent: Intent
    confidence: float
    alternatives: tuple[tuple[Intent, float], ...] = ()
    language: Language = Language.PT_BR
    method: ClassificationMethod = ClassificationMethod.KEYWORD
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON persistence / audit logs."""
        return {
            "intent": self.intent.value,
            "confidence": self.confidence,
            "alternatives": [{"intent": i.value, "score": s} for i, s in self.alternatives],
            "language": self.language.value,
            "method": self.method.value,
            "metadata": self.metadata,
        }


class LLMBackend(Protocol):
    """Minimal protocol for an LLM used as the disambiguation fallback."""

    def complete(self, prompt: str, **kwargs: Any) -> str: ...


@dataclass
class IntentClassifier:
    """Dual-stage NLU intent classifier for the Bradesco Bridge.

    Args:
        llm_backend: Optional LLM used to disambiguate queries whose
            keyword-baseline confidence is below
            ``llm_fallback_threshold``. If ``None`` the classifier is
            keyword-only.
        default_language: Language assumed when the caller does not
            specify one explicitly. Defaults to ``pt-BR`` because
            Bradesco's primary customer base is Brazilian.
        llm_fallback_threshold: Confidence below which the LLM is
            consulted (if available). Defaults to ``0.5``.
        ambiguity_margin: When the top score minus the second-best
            score is below this value, the LLM is consulted even if the
            top confidence is above ``llm_fallback_threshold``. Guards
            against confidently-wrong calls on lexically similar
            intents (e.g. ``pix`` vs ``transfer``).
    """

    llm_backend: LLMBackend | None = None
    default_language: Language = Language.PT_BR
    llm_fallback_threshold: float = 0.5
    ambiguity_margin: float = 0.15

    def classify(
        self,
        query: str,
        language: Language | str | None = None,
    ) -> IntentResult:
        """Classify a customer query into a banking intent.

        Args:
            query: Customer message in natural language.
            language: Language hint. Accepts a :class:`Language` value
                or its string form (``"pt-BR"`` / ``"en"``). When
                ``None`` the classifier's ``default_language`` is used.

        Returns:
            An :class:`IntentResult` carrying the top intent, a
            calibrated confidence, the runner-up alternatives, and the
            method used to reach the decision.
        """
        lang = self._resolve_language(language)
        normalized = self._normalize(query)

        if not normalized:
            _LOG.debug("intent.empty_query")
            return IntentResult(
                intent=Intent.GENERAL,
                confidence=0.0,
                language=lang,
                method=ClassificationMethod.DEFAULT,
                metadata={"reason": "empty_query"},
            )

        scores, matched = self._score_keywords(normalized, lang)
        ranking = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top_intent, top_score = ranking[0]
        runner_up_score = ranking[1][1] if len(ranking) > 1 else 0.0

        total = sum(score for _, score in ranking if score > 0)
        confidence = (top_score / total) if total > 0 else 0.0
        margin = top_score - runner_up_score

        if top_score <= 0:
            _LOG.info(
                "intent.no_match",
                language=lang.value,
                query=query[:80],
            )
            return IntentResult(
                intent=Intent.GENERAL,
                confidence=0.0,
                alternatives=(),
                language=lang,
                method=ClassificationMethod.DEFAULT,
                metadata={"matched_keywords": []},
            )

        alternatives = tuple((intent, score) for intent, score in ranking[1:4] if score > 0)

        needs_llm = self.llm_backend is not None and (
            confidence < self.llm_fallback_threshold or margin < self.ambiguity_margin
        )

        if needs_llm:
            llm_result = self._llm_disambiguate(
                query=query,
                language=lang,
                candidates=[intent for intent, _ in ranking if scores[intent] > 0],
                keyword_top=top_intent,
                keyword_confidence=confidence,
                matched=matched,
            )
            if llm_result is not None:
                return llm_result

        _LOG.info(
            "intent.classified",
            intent=top_intent.value,
            confidence=f"{confidence:.3f}",
            language=lang.value,
            method=ClassificationMethod.KEYWORD.value,
        )
        return IntentResult(
            intent=top_intent,
            confidence=confidence,
            alternatives=alternatives,
            language=lang,
            method=ClassificationMethod.KEYWORD,
            metadata={"matched_keywords": matched.get(top_intent, [])},
        )

    def _resolve_language(self, language: Language | str | None) -> Language:
        if language is None:
            return self.default_language
        if isinstance(language, Language):
            return language
        try:
            return Language(language)
        except ValueError:
            _LOG.warning(
                "intent.unknown_language",
                received=str(language),
                fallback=self.default_language.value,
            )
            return self.default_language

    @staticmethod
    def _normalize(query: str) -> str:
        return query.strip().lower()

    @staticmethod
    def _score_keywords(
        normalized: str,
        language: Language,
    ) -> tuple[dict[Intent, float], dict[Intent, list[str]]]:
        """Score every intent against the normalized query.

        A longer keyword (more specific) scores higher than a short one
        so that ``"chave pix"`` outranks a generic ``"pix"`` substring
        match. Each hit contributes ``len(keyword)`` to that intent's
        score.
        """
        table = _KEYWORDS_BY_LANGUAGE[language]
        scores: dict[Intent, float] = dict.fromkeys(table, 0.0)
        matched: dict[Intent, list[str]] = {intent: [] for intent in table}

        for intent, keywords in table.items():
            for keyword in keywords:
                if keyword in normalized:
                    scores[intent] += float(len(keyword))
                    matched[intent].append(keyword)

        return scores, matched

    def _llm_disambiguate(
        self,
        *,
        query: str,
        language: Language,
        candidates: list[Intent],
        keyword_top: Intent,
        keyword_confidence: float,
        matched: dict[Intent, list[str]],
    ) -> IntentResult | None:
        """Ask the LLM to pick one intent from the candidate set.

        Returns ``None`` if the LLM call fails or its response cannot be
        parsed -- the caller then falls back to the keyword result so
        the platform never blocks on a flaky LLM.
        """
        assert self.llm_backend is not None  # narrowed by caller

        candidate_list = [c.value for c in candidates] or [i.value for i in Intent]
        prompt = (
            "You are an intent classifier for a Brazilian retail bank. "
            "Pick the single best intent for the customer message from "
            "the list. Reply with ONLY the intent label, lowercase, no "
            "punctuation.\n\n"
            f"Allowed intents: {', '.join(candidate_list)}\n"
            f"Language: {language.value}\n"
            f"Customer message: {query}\n"
            "Intent:"
        )

        try:
            raw = self.llm_backend.complete(prompt)
        except Exception as exc:
            _LOG.error(
                "intent.llm_error",
                error=str(exc),
                keyword_top=keyword_top.value,
            )
            return None

        chosen = self._parse_llm_response(raw, candidates)
        if chosen is None:
            _LOG.warning(
                "intent.llm_unparseable",
                raw=str(raw)[:120],
                keyword_top=keyword_top.value,
            )
            return None

        _LOG.info(
            "intent.classified",
            intent=chosen.value,
            confidence="0.900",
            language=language.value,
            method=ClassificationMethod.LLM_FALLBACK.value,
            keyword_top=keyword_top.value,
            keyword_confidence=f"{keyword_confidence:.3f}",
        )
        return IntentResult(
            intent=chosen,
            confidence=0.9,
            alternatives=tuple((c, 0.0) for c in candidates if c is not chosen)[:3],
            language=language,
            method=ClassificationMethod.LLM_FALLBACK,
            metadata={
                "keyword_top": keyword_top.value,
                "keyword_confidence": keyword_confidence,
                "matched_keywords": matched.get(keyword_top, []),
                "llm_raw": str(raw)[:200],
            },
        )

    @staticmethod
    def _parse_llm_response(raw: str, candidates: list[Intent]) -> Intent | None:
        """Extract an :class:`Intent` from a free-form LLM reply.

        Strategy: lowercase the reply, then look for any candidate
        intent's value as a substring. Returns the first hit -- LLMs
        sometimes wrap the answer in quotes or add a period.
        """
        if not raw:
            return None
        text = raw.strip().lower()
        if not text:
            return None

        allowed = set(candidates) if candidates else set(Intent)
        for intent in allowed:
            if intent.value in text:
                return intent
        return None


__all__ = [
    "ClassificationMethod",
    "IntentClassifier",
    "IntentResult",
    "Language",
    "LLMBackend",
]
