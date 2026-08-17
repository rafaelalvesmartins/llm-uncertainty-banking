# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Banking chatbot agent with uncertainty guardrails.

Customer-facing conversational agent for the Bradesco Bridge platform.
Every response is gated by an uncertainty signal — when confidence falls
below the configured threshold the query is escalated rather than
returning an unreliable answer.

Escalation is a cascade, not a dead end. With an ``escalation_backend``
configured the agent defers the *verbatim* question to a stronger tier
via :class:`~lub.orchestration.router.TieredRouter`; only when that tier
is also uncertain does the query reach a human, and it arrives with both
drafts attached. Without one the agent keeps the legacy single-tier
behaviour (canned handoff message).

The agent connects to the LUB framework through an injectable
``confidence_estimator`` callable. Production deployments wire any of
the 20+ estimators in :mod:`lub.uncertainty` (semantic entropy,
self-consistency, conformal, P(true), perplexity, eigen-score, ...) by
adapting them to the ``(prompt, answer) -> float`` signature. When no
estimator is provided the agent falls back to a deliberately simple
keyword/length heuristic so the unit tests and dev sandbox stay
self-contained.

Example wiring against a LUB estimator::

    from lub.uncertainty.semantic_entropy import SemanticEntropyEstimator

    est = SemanticEntropyEstimator(backend=my_llm)

    def chatbot_confidence(prompt: str, answer: str) -> float:
        return est.estimate(prompt, answer).confidence

    agent = ChatbotAgent(
        backend=my_llm,
        confidence_estimator=chatbot_confidence,
        confidence_threshold=0.7,
    )

Reference: Bradesco Bridge achieves 83% resolution rate and 89% retention
without escalation across millions of daily customer interactions.
"""

# bridge-governance: upstream -- customer text is governed by BridgePlatform.process_query (bridge-ui/backend/server.py: _GOVERNOR.govern at the BFF). Agent sees masked text. See DATA_GOVERNANCE.md section 4a.
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

import structlog

from lub.orchestration.router import ABSTAIN_TIER, Tier, TieredRouter
from lub.types import UncertaintyResult

_LOG = structlog.get_logger("lub.agents.chatbot")

PRIMARY_TIER = "primary"
ESCALATION_TIER = "escalation"

_HUMAN_HANDOFF_MESSAGE = (
    "Vou transferir sua solicitacao para um especialista que podera ajuda-lo melhor."
)


class Intent(StrEnum):
    """Banking customer intent categories."""

    BALANCE = "balance"
    TRANSFER = "transfer"
    LOAN = "loan"
    COMPLAINT = "complaint"
    INVESTMENT = "investment"
    PIX = "pix"
    CARD = "card"
    GENERAL = "general"


_INTENT_KEYWORDS: dict[Intent, list[str]] = {
    Intent.BALANCE: ["saldo", "balance", "extrato", "statement", "quanto tenho"],
    Intent.TRANSFER: ["transferir", "transfer", "enviar", "send", "ted", "doc"],
    Intent.LOAN: ["emprestimo", "loan", "credito", "credit", "financiamento"],
    Intent.COMPLAINT: ["reclamacao", "complaint", "problema", "issue", "error"],
    Intent.INVESTMENT: ["investimento", "investment", "cdb", "tesouro", "fundo"],
    Intent.PIX: ["pix", "chave pix", "pix key"],
    Intent.CARD: ["cartao", "card", "fatura", "bill", "limite", "limit"],
}


ConfidenceEstimator = Callable[[str, str], float]
"""Signature for an injectable confidence estimator.

Takes ``(prompt, answer)`` and returns a calibrated confidence in
``[0, 1]``. Adapters over :mod:`lub.uncertainty` estimators fit this
shape with a one-line lambda; see the module docstring.
"""


@dataclass(frozen=True)
class ChatResponse:
    """Response from the chatbot agent.

    Attributes:
        answer: The generated response text.
        confidence: Model confidence in [0, 1].
        intent: Classified customer intent.
        escalated: True if confidence was below threshold and query
            was routed to a human operator.
        session_id: Conversation session identifier.
        metadata: Additional context (model used, latency, etc.).
    """

    answer: str
    confidence: float
    intent: Intent
    escalated: bool = False
    session_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary for JSON persistence."""
        return {
            "answer": self.answer,
            "confidence": self.confidence,
            "intent": self.intent.value,
            "escalated": self.escalated,
            "session_id": self.session_id,
            "metadata": self.metadata,
        }


class LLMBackend(Protocol):
    """Minimal protocol for an LLM backend that the chatbot can call."""

    def complete(self, prompt: str, **kwargs: Any) -> str: ...


@dataclass
class _TierPipeline:
    """Adapt ``(LLMBackend, scorer)`` to the pipeline shape TieredRouter wants.

    Keeps :attr:`last` so the human-review package can quote what this
    tier actually drafted — :class:`~lub.orchestration.router.RouterResult`
    records per-tier *confidences*, not per-tier *answers*.
    """

    backend: LLMBackend
    score: Callable[[str, str], tuple[float, str]]
    name: str = ""
    last: UncertaintyResult | None = None

    def answer(self, prompt: str, **kwargs: Any) -> UncertaintyResult:
        text = self.backend.complete(prompt, **kwargs)
        confidence, source = self.score(prompt, text)
        self.last = UncertaintyResult(
            answer=text,
            confidence=confidence,
            diagnostics={"confidence_source": source},
        )
        return self.last

    def batch_answer(self, prompts: list[str], **kwargs: Any) -> list[UncertaintyResult]:
        """Score prompts in sequence (``PipelineProto``)."""
        return [self.answer(p, **kwargs) for p in prompts]

    def to_dict(self) -> dict[str, Any]:
        """Describe the tier for the audit record (``PipelineProto``).

        Not round-trippable: the backend is an injected live object, not
        a reconstructible config. Enough to say *which* tier ran.
        """
        return {
            "backend": type(self.backend).__name__,
            "model": self.name,
            "estimator": "chatbot_confidence",
        }


@dataclass
class ChatbotAgent:
    """Customer chatbot agent with uncertainty guardrails.

    Args:
        backend: LLM backend implementing the complete() protocol.
        confidence_threshold: Minimum confidence to return an answer
            directly. Below this threshold the query is escalated.
        system_prompt: System prompt prepended to every query.
        confidence_estimator: Optional ``(prompt, answer) -> float``
            callable that supplies a calibrated confidence. Wire this
            to any :mod:`lub.uncertainty` estimator (semantic entropy,
            self-consistency, conformal, ...) so the escalation
            decision uses a real LUB signal rather than the fallback
            heuristic. When ``None`` a keyword/length heuristic is
            used — sufficient for tests and dev, NOT for production.
        escalation_backend: Optional stronger LLM backend. When set, a
            below-threshold answer is re-asked to this tier with the
            customer's question unchanged, and only a second failure
            reaches a human. When ``None`` the agent keeps the legacy
            single-tier behaviour.
        escalation_threshold: Confidence bar the escalation tier must
            clear. Defaults to ``confidence_threshold`` — set it higher
            to demand more of the expensive model than of the cheap one.
        primary_cost: Per-call cost of ``backend``, for accounting only.
        escalation_cost: Per-call cost of ``escalation_backend``. Only
            charged when that tier actually runs.
    """

    backend: LLMBackend
    confidence_threshold: float = 0.7
    system_prompt: str = (
        "You are a helpful banking assistant for Banco Bradesco. "
        "Answer customer questions accurately and concisely. "
        "If you are unsure, say so - do not fabricate information."
    )
    confidence_estimator: ConfidenceEstimator | None = None
    escalation_backend: LLMBackend | None = None
    escalation_threshold: float | None = None
    primary_cost: float = 0.0
    escalation_cost: float = 0.0

    def classify_intent(self, query: str) -> Intent:
        """Classify the customer query into a banking intent category."""
        query_lower = query.lower()
        for intent, keywords in _INTENT_KEYWORDS.items():
            if any(kw in query_lower for kw in keywords):
                _LOG.debug("intent.classified", intent=intent.value, query=query[:50])
                return intent
        return Intent.GENERAL

    def answer(
        self,
        query: str,
        *,
        session_id: str = "",
        channel: str = "app",
        **kwargs: Any,
    ) -> ChatResponse:
        """Answer a customer query with uncertainty guardrails.

        If the model's confidence is below ``confidence_threshold``, the
        response is marked as escalated and the answer contains an
        escalation message rather than the raw model output.

        Args:
            query: Customer question in natural language.
            session_id: Conversation session identifier.
            channel: Source channel (app, whatsapp, web).

        Returns:
            ChatResponse with answer, confidence, and escalation status.
        """
        intent = self.classify_intent(query)
        prompt = f"{self.system_prompt}\n\nCustomer ({channel}): {query}"

        _LOG.info(
            "chatbot.query",
            intent=intent.value,
            channel=channel,
            session_id=session_id,
        )

        if self.escalation_backend is not None:
            return self._answer_cascaded(
                prompt,
                intent=intent,
                session_id=session_id,
                channel=channel,
                **kwargs,
            )

        try:
            raw_answer = self.backend.complete(prompt, **kwargs)
        except Exception as exc:
            _LOG.error("chatbot.backend_error", error=str(exc))
            return ChatResponse(
                answer="Desculpe, estou com dificuldades tecnicas. Vou transferir para um atendente.",
                confidence=0.0,
                intent=intent,
                escalated=True,
                session_id=session_id,
                metadata={"error": str(exc), "channel": channel},
            )

        confidence, source = self._score_confidence(prompt, raw_answer, intent)

        if confidence < self.confidence_threshold:
            _LOG.info(
                "chatbot.escalated",
                confidence=f"{confidence:.3f}",
                threshold=f"{self.confidence_threshold:.3f}",
                intent=intent.value,
                source=source,
            )
            return ChatResponse(
                answer="Vou transferir sua solicitacao para um especialista que podera ajuda-lo melhor.",
                confidence=confidence,
                intent=intent,
                escalated=True,
                session_id=session_id,
                metadata={
                    "original_answer": raw_answer,
                    "channel": channel,
                    "confidence_source": source,
                },
            )

        return ChatResponse(
            answer=raw_answer,
            confidence=confidence,
            intent=intent,
            escalated=False,
            session_id=session_id,
            metadata={"channel": channel, "confidence_source": source},
        )

    def _answer_cascaded(
        self,
        prompt: str,
        *,
        intent: Intent,
        session_id: str,
        channel: str,
        **kwargs: Any,
    ) -> ChatResponse:
        """Dispatch through primary -> escalation -> human and project the result.

        The cascade itself is :class:`~lub.orchestration.router.TieredRouter`;
        this method only adapts the backends to it and maps its
        :class:`~lub.orchestration.router.RouterResult` onto the
        customer-facing :class:`ChatResponse`.
        """
        assert self.escalation_backend is not None  # noqa: S101 — checked by caller.

        def score(p: str, a: str) -> tuple[float, str]:
            return self._score_confidence(p, a, intent)

        primary = _TierPipeline(self.backend, score, name=PRIMARY_TIER)
        escalation = _TierPipeline(self.escalation_backend, score, name=ESCALATION_TIER)
        escalation_threshold = (
            self.confidence_threshold
            if self.escalation_threshold is None
            else self.escalation_threshold
        )
        router = TieredRouter(
            tiers=[
                Tier(
                    PRIMARY_TIER,
                    primary,
                    threshold=self.confidence_threshold,
                    cost=self.primary_cost,
                ),
                Tier(
                    ESCALATION_TIER,
                    escalation,
                    threshold=escalation_threshold,
                    cost=self.escalation_cost,
                ),
            ]
        )

        try:
            routed = router.answer(prompt, **kwargs)
        except Exception as exc:
            _LOG.error("chatbot.backend_error", error=str(exc))
            return ChatResponse(
                answer="Desculpe, estou com dificuldades tecnicas. Vou transferir para um atendente.",
                confidence=0.0,
                intent=intent,
                escalated=True,
                session_id=session_id,
                metadata={"error": str(exc), "channel": channel},
            )

        metadata: dict[str, Any] = {
            "channel": channel,
            "confidence_source": routed.final.diagnostics.get("confidence_source", "unknown"),
            "tier_used": routed.tier_used,
            "escalation_path": routed.escalation_path,
            "total_cost": routed.total_cost,
        }

        if routed.tier_used == ABSTAIN_TIER:
            _LOG.info(
                "chatbot.escalated.human",
                best_confidence=f"{routed.final.confidence:.3f}",
                intent=intent.value,
                cost=routed.total_cost,
            )
            metadata["resolution"] = "human"
            metadata["human_review_required"] = True
            metadata["drafts"] = {
                PRIMARY_TIER: primary.last.answer if primary.last else None,
                ESCALATION_TIER: escalation.last.answer if escalation.last else None,
            }
            return ChatResponse(
                answer=_HUMAN_HANDOFF_MESSAGE,
                confidence=routed.final.confidence,
                intent=intent,
                escalated=True,
                session_id=session_id,
                metadata=metadata,
            )

        escalated = routed.tier_used != PRIMARY_TIER
        if escalated:
            _LOG.info(
                "chatbot.escalated.tier",
                tier=routed.tier_used,
                confidence=f"{routed.final.confidence:.3f}",
                intent=intent.value,
                cost=routed.total_cost,
            )
        metadata["resolution"] = routed.tier_used
        return ChatResponse(
            answer=routed.final.answer,
            confidence=routed.final.confidence,
            intent=intent,
            escalated=escalated,
            session_id=session_id,
            metadata=metadata,
        )

    def _score_confidence(self, prompt: str, answer: str, intent: Intent) -> tuple[float, str]:
        """Return ``(confidence, source)`` using the injected estimator if any.

        If ``confidence_estimator`` is configured, call it; on success
        clamp to ``[0, 1]`` and tag the source as ``"estimator"``. If
        the estimator raises or returns a non-numeric value, fall back
        to the heuristic and tag the source as ``"heuristic_fallback"``
        so the audit trail records the degradation.
        """
        if self.confidence_estimator is not None:
            try:
                raw = float(self.confidence_estimator(prompt, answer))
            except Exception as exc:
                _LOG.warning(
                    "chatbot.confidence_estimator_error",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                return self._estimate_confidence(answer, intent), "heuristic_fallback"
            clamped = max(0.0, min(1.0, raw))
            return clamped, "estimator"
        return self._estimate_confidence(answer, intent), "heuristic"

    def _estimate_confidence(self, answer: str, intent: Intent) -> float:
        """Heuristic confidence used when no estimator is injected.

        Keyword/length stub for tests and the dev sandbox. Production
        deployments must pass ``confidence_estimator`` so this branch
        is never taken — it is intentionally crude to make accidental
        production use easy to spot in calibration plots.
        """
        if not answer or len(answer.strip()) < 10:
            return 0.1
        hedging = ["nao tenho certeza", "talvez", "possibly", "i'm not sure", "uncertain"]
        if any(h in answer.lower() for h in hedging):
            return 0.4
        return 0.85


__all__ = ["ChatResponse", "ChatbotAgent", "ConfidenceEstimator", "Intent"]
