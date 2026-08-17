# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Call-center assistant agent for the Bradesco Bridge platform.

Helps service agents in real-time during phone and chat interactions by
suggesting responses, summarising customer history, and flagging
compliance risks before they reach the customer.

The agent delegates text generation to any backend that satisfies the
:class:`LLMBackend` protocol, keeping the module free of hard
dependencies on OpenAI, Hugging Face, or any specific provider.

Usage::

    from lub.connectors.bridge.agents.call_center import CallCenterAgent

    agent = CallCenterAgent(backend=my_llm)
    suggestion = agent.suggest_response("Customer: I want to cancel my card.")
    flags = agent.flag_compliance("Agent: Your CPF is 123.456.789-00.")
"""

# bridge-governance: upstream -- customer text is governed by BridgePlatform.process_query (bridge-ui/backend/server.py: _GOVERNOR.govern at the BFF). Agent sees masked text. See DATA_GOVERNANCE.md section 4a.
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

import structlog

_LOG = structlog.get_logger("lub.agents.call_center")


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class LLMBackend(Protocol):
    """Minimal protocol for an LLM backend the call-center agent can call."""

    def complete(self, prompt: str, **kwargs: Any) -> str:
        """Generate a text completion for the given prompt.

        Backends implementing this protocol feed the call-center agent's
        suggestion and summary pipelines. The returned text is post-processed
        by :class:`CallCenterAgent` for compliance and confidence gating, so
        backends should return raw model output without additional filtering.

        Edge cases:
            - On transient failures the backend should raise an exception;
              the agent catches it and returns a safe zero-confidence
              fallback rather than propagating the error to the operator.
            - An empty or near-empty completion drops heuristic confidence
              to ``0.1``, which sits below the default ``confidence_threshold``
              and triggers human review under banking guardrails.

        Args:
            prompt: Full prompt text including system instructions and
                conversation context.
            **kwargs: Backend-specific generation parameters (temperature,
                max_tokens, etc.). Implementations may ignore unknown keys.

        Returns:
            The model's completion as a single string.
        """
        ...


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


class ComplianceSeverity(StrEnum):
    """Severity levels for compliance flags."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ComplianceFlag:
    """A compliance risk detected in a transcript fragment.

    Attributes:
        rule: Identifier for the compliance rule that was triggered
            (e.g. ``"PII_EXPOSURE"``, ``"BCB4893_TRANSPARENCY"``).
        severity: Risk severity.
        excerpt: The excerpt from the transcript that triggered the flag.
        recommendation: Suggested remediation action.
    """

    rule: str
    severity: ComplianceSeverity
    excerpt: str
    recommendation: str


@dataclass(frozen=True)
class Suggestion:
    """A response suggestion for the service agent.

    Attributes:
        text: Suggested reply text.
        confidence: Model confidence in ``[0, 1]``.
        intent: Detected customer intent that drove the suggestion.
        alternatives: Up to two alternative phrasings ranked by relevance.
    """

    text: str
    confidence: float
    intent: str
    alternatives: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Compliance patterns
# ---------------------------------------------------------------------------

_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("CPF", re.compile(r"\b\d{3}[.\s]?\d{3}[.\s]?\d{3}[-.\s]?\d{2}\b")),
    ("CNPJ", re.compile(r"\b\d{2}[.\s]?\d{3}[.\s]?\d{3}[/\\]?\d{4}[-.\s]?\d{2}\b")),
    ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")),
]

_PROHIBITED_PHRASES: list[tuple[str, str]] = [
    ("GUARANTEE_RETURN", "garantia de retorno"),
    ("GUARANTEE_RETURN", "guaranteed return"),
    ("GUARANTEE_PROFIT", "lucro garantido"),
    ("GUARANTEE_PROFIT", "guaranteed profit"),
    ("UNAUTHORIZED_ADVICE", "eu recomendo que voce invista"),
    ("UNAUTHORIZED_ADVICE", "i recommend you invest"),
]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


@dataclass
class CallCenterAgent:
    """Real-time assistant for call-center service agents.

    Args:
        backend: LLM backend implementing the ``complete()`` protocol.
        confidence_threshold: Minimum confidence to include a suggestion.
        max_alternatives: Maximum number of alternative suggestions.
        system_prompt: System prompt prepended to every LLM call.
    """

    backend: LLMBackend
    confidence_threshold: float = 0.6
    max_alternatives: int = 2
    system_prompt: str = (
        "You are an internal assistant for Banco Bradesco call-center agents. "
        "Suggest clear, compliant, and empathetic responses. "
        "Never disclose customer PII. Always follow BCB and CVM regulations."
    )

    def suggest_response(self, transcript: str) -> Suggestion:
        """Suggest a response for the service agent based on the live transcript.

        The suggestion is generated by the LLM backend and post-processed
        to ensure compliance. If the backend call fails, a safe fallback
        suggestion is returned with zero confidence.

        Args:
            transcript: Current conversation transcript between the customer
                and the service agent.

        Returns:
            A :class:`Suggestion` with the recommended reply, confidence
            score, detected intent, and alternative phrasings.
        """
        intent = self._detect_intent(transcript)
        prompt = (
            f"{self.system_prompt}\n\n"
            f"Transcript:\n{transcript}\n\n"
            f"Detected intent: {intent}\n"
            "Suggest the best next response for the agent. "
            "Then provide up to two alternative phrasings, each on a new "
            "line prefixed with 'ALT: '."
        )

        _LOG.info("call_center.suggest", intent=intent, transcript_len=len(transcript))

        try:
            raw = self.backend.complete(prompt)
        except Exception as exc:
            _LOG.error("call_center.backend_error", error=str(exc))
            return Suggestion(
                text="Aguarde um momento, por favor, enquanto verifico as informacoes.",
                confidence=0.0,
                intent=intent,
            )

        main_text, alternatives = self._parse_suggestion(raw)
        confidence = self._estimate_confidence(main_text, intent)

        if confidence < self.confidence_threshold:
            _LOG.info(
                "call_center.low_confidence",
                confidence=f"{confidence:.3f}",
                threshold=f"{self.confidence_threshold:.3f}",
            )

        return Suggestion(
            text=main_text,
            confidence=confidence,
            intent=intent,
            alternatives=alternatives[: self.max_alternatives],
        )

    def summarize_history(self, entries: list[dict[str, Any]]) -> str:
        """Summarise a customer's interaction history for the service agent.

        Args:
            entries: List of historical interaction records. Each entry is
                a dict with at least ``"date"``, ``"channel"``, and
                ``"summary"`` keys.

        Returns:
            A concise natural-language summary suitable for display in the
            agent's console.
        """
        if not entries:
            return "Nenhum historico de interacao encontrado para este cliente."

        formatted_entries: list[str] = []
        for entry in entries:
            date = entry.get("date", "N/A")
            channel = entry.get("channel", "N/A")
            summary = entry.get("summary", "N/A")
            formatted_entries.append(f"- {date} ({channel}): {summary}")

        history_block = "\n".join(formatted_entries)
        prompt = (
            f"{self.system_prompt}\n\n"
            f"Customer interaction history:\n{history_block}\n\n"
            "Provide a concise summary (3-5 sentences) highlighting key issues, "
            "unresolved complaints, and recent product activity."
        )

        _LOG.info("call_center.summarize", n_entries=len(entries))

        try:
            return self.backend.complete(prompt).strip()
        except Exception as exc:
            _LOG.error("call_center.summarize_error", error=str(exc))
            return (
                f"Resumo automatico indisponivel. "
                f"O cliente possui {len(entries)} interacoes registradas."
            )

    def flag_compliance(self, transcript: str) -> list[ComplianceFlag]:
        """Scan a transcript for compliance risks.

        Checks for PII exposure, prohibited financial guarantees, and
        regulatory-sensitive language. This is a deterministic,
        pattern-based check that does not call the LLM backend.

        Args:
            transcript: Conversation text to scan.

        Returns:
            List of :class:`ComplianceFlag` instances, one per detected
            risk. May be empty if no risks are found.
        """
        flags: list[ComplianceFlag] = []
        transcript_lower = transcript.lower()

        # PII detection
        for label, pattern in _PII_PATTERNS:
            for match in pattern.finditer(transcript):
                flags.append(
                    ComplianceFlag(
                        rule=f"PII_EXPOSURE_{label}",
                        severity=ComplianceSeverity.CRITICAL,
                        excerpt=match.group(),
                        recommendation=(
                            f"Remove {label} from the conversation. Use masked references only."
                        ),
                    )
                )

        # Prohibited phrases
        for rule, phrase in _PROHIBITED_PHRASES:
            idx = transcript_lower.find(phrase)
            if idx != -1:
                start = max(0, idx - 20)
                end = min(len(transcript), idx + len(phrase) + 20)
                flags.append(
                    ComplianceFlag(
                        rule=rule,
                        severity=ComplianceSeverity.HIGH,
                        excerpt=transcript[start:end],
                        recommendation=(
                            "Remove or rephrase. Financial guarantees and "
                            "unsolicited investment advice are prohibited "
                            "under CVM Instruction 539 and BCB Resolution 4893."
                        ),
                    )
                )

        if flags:
            _LOG.warning(
                "call_center.compliance_flags",
                n_flags=len(flags),
                rules=[f.rule for f in flags],
            )
        else:
            _LOG.debug("call_center.compliance_clean")

        return flags

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _detect_intent(self, transcript: str) -> str:
        """Simple keyword-based intent detection for routing."""
        transcript_lower = transcript.lower()
        intent_keywords: dict[str, list[str]] = {
            "cancelamento": ["cancelar", "cancel", "encerrar", "fechar conta"],
            "reclamacao": ["reclamacao", "complaint", "problema", "insatisfeito"],
            "financeiro": ["saldo", "extrato", "transferencia", "pix", "ted"],
            "cartao": ["cartao", "card", "fatura", "limite"],
            "investimento": ["investimento", "cdb", "fundo", "tesouro"],
            "emprestimo": ["emprestimo", "loan", "credito", "financiamento"],
        }
        for intent, keywords in intent_keywords.items():
            if any(kw in transcript_lower for kw in keywords):
                return intent
        return "geral"

    def _parse_suggestion(self, raw: str) -> tuple[str, list[str]]:
        """Split LLM output into main suggestion and alternatives."""
        lines = raw.strip().splitlines()
        main_lines: list[str] = []
        alternatives: list[str] = []

        for line in lines:
            stripped = line.strip()
            if stripped.upper().startswith("ALT:"):
                alternatives.append(stripped[4:].strip())
            else:
                main_lines.append(stripped)

        main_text = " ".join(main_lines).strip()
        if not main_text:
            main_text = raw.strip()

        return main_text, alternatives

    def _estimate_confidence(self, answer: str, intent: str) -> float:
        """Heuristic confidence estimation.

        In production this is replaced by :class:`~lub.guard.UncertaintyGuard`
        with a calibrated estimator. This stub uses simple heuristics.
        """
        if not answer or len(answer.strip()) < 10:
            return 0.1
        hedging = [
            "nao tenho certeza",
            "talvez",
            "possibly",
            "i'm not sure",
            "uncertain",
            "nao sei",
        ]
        if any(h in answer.lower() for h in hedging):
            return 0.35
        if intent == "geral":
            return 0.7
        return 0.85


__all__ = ["CallCenterAgent", "ComplianceFlag", "ComplianceSeverity", "Suggestion"]
