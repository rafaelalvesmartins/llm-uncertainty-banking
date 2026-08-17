# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""AI governance framework for the Bradesco Bridge platform.

Bradesco Bridge sits in the path of regulated customer-facing channels
(WhatsApp, call center, mobile app), so every prompt that reaches an
LLM and every completion that leaves one must pass a *defense-in-depth*
governance layer. The :class:`~lub.guard.UncertaintyGuard` answers the
question "is the model confident enough to speak?"; this module answers
the orthogonal three:

1. *Is the input safe to send to the model?* — :class:`PromptGuard`
   blocks prompt-injection and jailbreak attempts that would otherwise
   make the model bypass its system prompt or leak privileged data.
2. *Is the output safe to send to the customer?* — :class:`ContentSafetyFilter`
   inspects model completions for harmful content (hate, violence,
   sexual, self-harm) and for banking-specific data leaks (CPF/CNPJ,
   full card numbers, full account numbers).
3. *Is the request within Bridge's scope?* — :class:`IntentClassifier`
   refuses queries that fall outside banking topics (medical, legal,
   personal advice, generic chat). Out-of-scope queries are not just a
   product concern — answering them creates *unspecified-purpose*
   automated decisions that are hard to defend under SR 11-7 model-risk
   review.

The design follows the Azure AI Content Safety taxonomy (Microsoft's
reference for the Bradesco deployment) but keeps the implementation
dependency-free: every check runs on regex/keyword heuristics so the
governance layer continues to function when the upstream Azure service
is unreachable. Higher-fidelity classifiers can be plugged in via the
``external_classifier`` hook on :class:`ContentSafetyFilter` without
changing the public API.

Regulatory framing
------------------

* **BCB Resolução 4.893** — operational risk and customer protection:
  every blocked input/output is logged with category, severity, and
  matched pattern so the bank can demonstrate the AI channel refuses
  to act on unsafe inputs.
* **BCBS 239** — risk data aggregation: governance verdicts share a
  common envelope (:class:`GovernanceVerdict`) so they can be rolled
  up across agents, channels, and time windows.
* **SR 11-7** — model risk management: scope-validation refusals keep
  the production model inside the use cases for which it was
  validated, preventing silent capability creep.
* **LGPD (Lei Geral de Proteção de Dados)** — the PII leak rules in
  :class:`ContentSafetyFilter` directly serve the LGPD article 6 data-
  minimization principle by ensuring sensitive identifiers are never
  echoed back to a customer or stored in a transcript.

Design contract
---------------

All public ``check_*`` / ``validate_*`` methods are *total*: they
return a result envelope even when their internal heuristics fail.
A governance check that itself raises is a worse failure mode than
one that returns ``REVIEW`` with an explanatory reason — bridge code
should always have a verdict to log, even if that verdict is
"escalate to human, governance subsystem degraded".
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "ContentCategory",
    "ContentSafetyFilter",
    "GovernanceError",
    "GovernancePipeline",
    "GovernanceVerdict",
    "IntentClassifier",
    "IntentResult",
    "PromptGuard",
    "PromptSafetyResult",
    "SafetyResult",
    "SafetySeverity",
    "SafetyVerdict",
    "ScopeDomain",
]

_LOG = structlog.get_logger("lub.bridge.governance")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GovernanceError(RuntimeError):
    """Raised when a governance component cannot meet its contract.

    Intentionally rare — public ``check_*`` methods catch their own
    failures and downgrade to ``REVIEW``. This error is reserved for
    programmer-error conditions (e.g., supplying a non-string prompt)
    so callers don't accidentally treat a misuse as a banking refusal.
    """


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SafetyVerdict(StrEnum):
    """Outcome of a single governance check.

    Three values rather than a boolean: a banking-grade governance
    layer must distinguish ``SAFE`` (return to customer), ``UNSAFE``
    (block and log) and ``REVIEW`` (suppress automated answer, route
    to human). Boolean checks force borderline cases into one of the
    two extremes and lose audit fidelity.
    """

    SAFE = "safe"
    UNSAFE = "unsafe"
    REVIEW = "review"


class SafetySeverity(StrEnum):
    """Severity bucket used by :class:`ContentSafetyFilter`.

    Aligned with Azure AI Content Safety's 0/2/4/6 severity scale but
    expressed as ordinal names so downstream callers don't depend on
    Microsoft-specific numerics. ``NONE`` exists so a result can carry
    a severity even when the verdict is :attr:`SafetyVerdict.SAFE`.
    """

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ContentCategory(StrEnum):
    """Categories inspected by :class:`ContentSafetyFilter`.

    The first four mirror the Azure AI Content Safety taxonomy. The
    last two are banking-specific: Bradesco-relevant data leaks
    (CPF/CNPJ, card numbers, PIX keys) that have no Azure equivalent
    and would otherwise need a custom classifier per regulator.
    """

    HATE = "hate"
    VIOLENCE = "violence"
    SEXUAL = "sexual"
    SELF_HARM = "self_harm"
    PROFANITY = "profanity"
    PII_LEAK = "pii_leak"


class ScopeDomain(StrEnum):
    """High-level domains the intent classifier knows about.

    Only :attr:`BANKING` is in-scope for Bridge. The others are
    enumerated explicitly (rather than collapsed to ``OUT_OF_SCOPE``)
    so audit reviewers can see *why* a query was refused — useful for
    product analytics that want to find unmet customer needs without
    silently accepting them.
    """

    BANKING = "banking"
    MEDICAL = "medical"
    LEGAL = "legal"
    POLITICAL = "political"
    GENERIC = "generic"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Result envelopes
# ---------------------------------------------------------------------------


class SafetyResult(BaseModel):
    """Verdict from :meth:`ContentSafetyFilter.check_content`."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    verdict: SafetyVerdict
    categories: tuple[ContentCategory, ...] = Field(default_factory=tuple)
    severity: SafetySeverity = SafetySeverity.NONE
    reasons: tuple[str, ...] = Field(default_factory=tuple)
    redacted: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def safe(self) -> bool:
        """Convenience flag: True when the verdict is :attr:`SafetyVerdict.SAFE`."""
        return self.verdict == SafetyVerdict.SAFE


class PromptSafetyResult(BaseModel):
    """Verdict from :meth:`PromptGuard.check_prompt`."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    verdict: SafetyVerdict
    injection_detected: bool = False
    matched_patterns: tuple[str, ...] = Field(default_factory=tuple)
    reasons: tuple[str, ...] = Field(default_factory=tuple)
    severity: SafetySeverity = SafetySeverity.NONE
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def safe(self) -> bool:
        """Convenience flag: True when the verdict is :attr:`SafetyVerdict.SAFE`."""
        return self.verdict == SafetyVerdict.SAFE


class IntentResult(BaseModel):
    """Verdict from :meth:`IntentClassifier.classify_intent`."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    domain: ScopeDomain
    in_scope: bool
    confidence: float = 0.0
    matched_terms: tuple[str, ...] = Field(default_factory=tuple)
    reasons: tuple[str, ...] = Field(default_factory=tuple)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return 0.0
        if v != v:  # NaN
            return 0.0
        return max(0.0, min(1.0, v))


class GovernanceVerdict(BaseModel):
    """Aggregated verdict from :class:`GovernancePipeline`.

    Combines the three component checks into a single envelope so
    callers (typically :class:`~lub.bridge.BridgePlatform`) can switch
    on a single ``allowed`` flag while still retaining the per-check
    detail required for the audit trail.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    allowed: bool
    prompt_safety: PromptSafetyResult | None = None
    content_safety: SafetyResult | None = None
    intent: IntentResult | None = None
    reasons: tuple[str, ...] = Field(default_factory=tuple)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Banking-aware regexes
# ---------------------------------------------------------------------------

# CPF: 11 digits, optionally formatted as XXX.XXX.XXX-XX.
_CPF_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\d)(\d{3}\.?\d{3}\.?\d{3}-?\d{2})(?!\d)")
# CNPJ: 14 digits, optionally formatted as XX.XXX.XXX/XXXX-XX.
_CNPJ_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\d)(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})(?!\d)")
# Card numbers: 13-19 contiguous digits (with optional separators).
_CARD_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
# Brazilian agency+account fragments (e.g., "ag 1234 cc 56789-0").
_ACCOUNT_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:ag(?:[eê]ncia)?|conta|cc|cp)[\s.:#-]*\d{3,6}[-/ ]?\d{0,2}\b"
)


# ---------------------------------------------------------------------------
# ContentSafetyFilter
# ---------------------------------------------------------------------------


# Keyword lists are intentionally small and Portuguese-leaning since the
# Bradesco customer base writes in PT-BR. They are NOT meant to be a
# moderation classifier — they exist so the pipeline returns a sensible
# verdict when no external classifier is wired in. Production deployments
# should pass an ``external_classifier`` that calls Azure AI Content
# Safety; this module's regexes are the floor, not the ceiling.
_HATE_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "racist",
        "racista",
        "nazi",
        "nazista",
        "supremacist",
        "preto imundo",
        "macaco safado",
    }
)
_VIOLENCE_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "kill yourself",
        "i will kill",
        "vou te matar",
        "vou matar",
        "shoot up",
        "atirar em todos",
        "bomb the",
        "explodir o",
    }
)
_SEXUAL_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "porn",
        "porno",
        "pornografia",
        "explicit sexual",
        "nude photos",
        "fotos nuas",
        "sexo explícito",
    }
)
_SELF_HARM_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "suicide",
        "suicídio",
        "kill myself",
        "me matar",
        "cut myself",
        "me cortar",
        "end my life",
        "acabar com minha vida",
    }
)
_PROFANITY_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "fuck",
        "shit",
        "asshole",
        "bitch",
        "porra",
        "caralho",
        "merda",
        "filho da puta",
        "fdp",
        "vai se foder",
    }
)


_ContentClassifier = Callable[[str], Mapping[ContentCategory, SafetySeverity]]


class ContentSafetyFilter:
    """Inspect model outputs (and optionally inputs) for unsafe content.

    Parameters
    ----------
    severity_threshold:
        Minimum severity at which a category is treated as a *block*.
        Anything strictly below this severity becomes ``REVIEW`` rather
        than ``UNSAFE``, so borderline outputs go to a human instead of
        being silently dropped. Defaults to :attr:`SafetySeverity.MEDIUM`.
    redact_pii:
        When ``True`` (the default), the result includes a ``redacted``
        copy of the input with detected PII replaced by ``[REDACTED]``.
        Bridge uses this when escalating to a human operator so the
        operator screen never displays raw customer identifiers.
    external_classifier:
        Optional callable that returns a ``{category: severity}`` map
        from a higher-fidelity service (e.g., Azure AI Content Safety).
        When supplied, its verdict is *merged* with the local heuristics
        — local rules can only escalate severity, never downgrade it.
        Exceptions raised by the classifier are caught and logged; the
        filter falls back to local heuristics rather than failing closed.

    Notes
    -----
    The filter is deliberately conservative on PII: any pattern match
    forces severity to :attr:`SafetySeverity.HIGH` and verdict to
    :attr:`SafetyVerdict.UNSAFE`. LGPD does not tolerate a "low-severity"
    PII leak.
    """

    def __init__(
        self,
        *,
        severity_threshold: SafetySeverity = SafetySeverity.MEDIUM,
        redact_pii: bool = True,
        external_classifier: _ContentClassifier | None = None,
    ) -> None:
        self._threshold = severity_threshold
        self._redact_pii = bool(redact_pii)
        self._external = external_classifier

    def check_content(self, text: str) -> SafetyResult:
        """Return a :class:`SafetyResult` for ``text``.

        Always returns a result — internal failures degrade to
        ``REVIEW`` with an explanatory reason rather than raising.
        """
        if not isinstance(text, str):
            raise GovernanceError(f"check_content requires a str, got {type(text).__name__}")

        if not text.strip():
            return SafetyResult(verdict=SafetyVerdict.SAFE)

        per_category: dict[ContentCategory, SafetySeverity] = {}
        reasons: list[str] = []

        # Local heuristic pass.
        for category, severity, reason in self._scan_keywords(text):
            per_category[category] = _max_severity(
                per_category.get(category, SafetySeverity.NONE), severity
            )
            reasons.append(reason)

        pii_categories, pii_reasons, redacted = self._scan_pii(text)
        for category in pii_categories:
            per_category[category] = SafetySeverity.HIGH
        reasons.extend(pii_reasons)

        # External classifier pass (best-effort merge).
        if self._external is not None:
            try:
                external = self._external(text)
            except Exception as exc:  # noqa: BLE001 — degrade, never fail closed
                _LOG.warning(
                    "bridge.governance.external_classifier_failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                reasons.append("external classifier unavailable; using local rules only")
            else:
                for category, severity in external.items():
                    if not isinstance(category, ContentCategory):
                        continue
                    per_category[category] = _max_severity(
                        per_category.get(category, SafetySeverity.NONE), severity
                    )

        if not per_category:
            return SafetyResult(verdict=SafetyVerdict.SAFE)

        worst = _worst_severity(per_category.values())
        verdict = self._verdict_for(worst)

        result = SafetyResult(
            verdict=verdict,
            categories=tuple(sorted(per_category, key=lambda c: c.value)),
            severity=worst,
            reasons=tuple(reasons),
            redacted=redacted if (self._redact_pii and redacted is not None) else None,
        )

        _LOG.info(
            "bridge.governance.content_checked",
            verdict=verdict.value,
            severity=worst.value,
            categories=[c.value for c in result.categories],
            redacted_pii=result.redacted is not None,
        )
        return result

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def _scan_keywords(
        text: str,
    ) -> Iterable[tuple[ContentCategory, SafetySeverity, str]]:
        lowered = text.lower()
        catalog: tuple[tuple[ContentCategory, frozenset[str], SafetySeverity], ...] = (
            (ContentCategory.HATE, _HATE_KEYWORDS, SafetySeverity.HIGH),
            (ContentCategory.VIOLENCE, _VIOLENCE_KEYWORDS, SafetySeverity.HIGH),
            (ContentCategory.SEXUAL, _SEXUAL_KEYWORDS, SafetySeverity.MEDIUM),
            (ContentCategory.SELF_HARM, _SELF_HARM_KEYWORDS, SafetySeverity.HIGH),
            (ContentCategory.PROFANITY, _PROFANITY_KEYWORDS, SafetySeverity.LOW),
        )
        for category, vocab, severity in catalog:
            for term in vocab:
                if term in lowered:
                    yield category, severity, f"matched {category.value} term '{term}'"
                    break

    @staticmethod
    def _scan_pii(
        text: str,
    ) -> tuple[list[ContentCategory], list[str], str | None]:
        reasons: list[str] = []
        redacted = text
        found = False

        for label, pattern in (
            ("CPF", _CPF_RE),
            ("CNPJ", _CNPJ_RE),
            ("card_number", _CARD_RE),
            ("account", _ACCOUNT_RE),
        ):
            if pattern.search(redacted):
                found = True
                reasons.append(f"detected {label} pattern")
                redacted = pattern.sub("[REDACTED]", redacted)

        if not found:
            return [], [], None
        return [ContentCategory.PII_LEAK], reasons, redacted

    def _verdict_for(self, severity: SafetySeverity) -> SafetyVerdict:
        if _severity_rank(severity) >= _severity_rank(self._threshold):
            return SafetyVerdict.UNSAFE
        if severity == SafetySeverity.NONE:
            return SafetyVerdict.SAFE
        return SafetyVerdict.REVIEW


# ---------------------------------------------------------------------------
# PromptGuard
# ---------------------------------------------------------------------------


# Patterns that strongly suggest a prompt-injection / jailbreak attempt.
# Sourced from the OWASP LLM Top 10 (LLM01: Prompt Injection) reference
# patterns, adapted for PT-BR phrasing common on Bradesco's WhatsApp
# channel. The list is *not* exhaustive — it's the conservative floor
# before an Azure Prompt Shield or similar service is plugged in.
_INJECTION_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "ignore_previous",
        re.compile(
            r"(?i)\b(?:ignore|disregard|forget|esqueça|ignorar?)\b"
            r".{0,30}\b(?:previous|prior|above|all|todas?|anterior(?:es)?|acima)\b"
            r".{0,40}\b(?:instructions?|prompts?|rules?|instruç(?:ão|ões)|regras?)\b"
        ),
    ),
    (
        "role_override",
        re.compile(
            r"(?i)\byou\s+are\s+now\b|"
            r"\bact\s+as\s+(?:a|an)\b|"
            r"\bpretend(?:\s+to\s+be|\s+you\s+are)\b|"
            r"\bvoc[eê]\s+(?:é|agora\s+é)\s+(?:um|uma)\b"
        ),
    ),
    (
        "system_prompt_probe",
        re.compile(
            r"(?i)\b(?:system\s+prompt|reveal\s+your\s+instructions?|"
            r"show\s+me\s+your\s+prompt|print\s+your\s+rules?|"
            r"mostre\s+(?:seu|suas?)\s+(?:prompt|instruç(?:ão|ões)|regras?))\b"
        ),
    ),
    (
        "developer_override",
        re.compile(
            r"(?i)\b(?:developer\s+mode|dan\s+mode|jailbreak|"
            r"do\s+anything\s+now|modo\s+desenvolvedor|modo\s+livre)\b"
        ),
    ),
    (
        "delimiter_smuggle",
        re.compile(
            r"(?:```\s*system\b|<\|system\|>|<\|im_start\|>system|"
            r"\[\[\s*system\s*\]\]|###\s*system\s*###)",
            re.IGNORECASE,
        ),
    ),
    (
        "credential_phishing",
        re.compile(
            r"(?i)\b(?:reveal|tell\s+me|share|me\s+(?:dê|d[eê])|envie)\b"
            r".{0,40}\b(?:password|senha|pin|token|api\s+key|chave\s+(?:de\s+)?api)\b"
        ),
    ),
)


@dataclass(frozen=True)
class _InjectionMatch:
    name: str
    excerpt: str


class PromptGuard:
    """Detect prompt-injection / jailbreak attempts before model dispatch.

    Parameters
    ----------
    extra_patterns:
        Optional iterable of ``(name, pattern)`` pairs added on top of
        the built-in patterns. Useful for tenant-specific policies (e.g.,
        a private-banking channel that wants to block any mention of
        competitor names) without monkey-patching the module.
    block_threshold:
        Minimum number of *distinct* matching patterns to escalate the
        verdict from ``REVIEW`` to ``UNSAFE``. Defaults to 1 — a single
        confident injection pattern is enough to block, matching the
        Microsoft Prompt Shields conservative posture.

    Notes
    -----
    The guard never *modifies* the prompt — it only labels it. Rewriting
    a customer's prompt to "make it safe" would create a record in the
    audit trail that does not match what the customer actually sent,
    which is itself a BCB 4893 reconstructability problem.
    """

    def __init__(
        self,
        *,
        extra_patterns: Sequence[tuple[str, re.Pattern[str]]] | None = None,
        block_threshold: int = 1,
    ) -> None:
        self._patterns: tuple[tuple[str, re.Pattern[str]], ...] = _INJECTION_PATTERNS + tuple(
            extra_patterns or ()
        )
        self._block_threshold = max(1, int(block_threshold))

    def check_prompt(self, prompt: str) -> PromptSafetyResult:
        """Return a :class:`PromptSafetyResult` for ``prompt``."""
        if not isinstance(prompt, str):
            raise GovernanceError(f"check_prompt requires a str, got {type(prompt).__name__}")

        if not prompt.strip():
            return PromptSafetyResult(verdict=SafetyVerdict.SAFE)

        matches: list[_InjectionMatch] = []
        for name, pattern in self._patterns:
            try:
                hit = pattern.search(prompt)
            except re.error as exc:
                _LOG.warning(
                    "bridge.governance.pattern_error",
                    pattern=name,
                    error=str(exc),
                )
                continue
            if hit is not None:
                excerpt = prompt[hit.start() : hit.end()][:120]
                matches.append(_InjectionMatch(name=name, excerpt=excerpt))

        if not matches:
            return PromptSafetyResult(verdict=SafetyVerdict.SAFE)

        names = tuple(m.name for m in matches)
        reasons = tuple(f"pattern '{m.name}' matched: {m.excerpt!r}" for m in matches)
        if len(set(names)) >= self._block_threshold:
            verdict = SafetyVerdict.UNSAFE
            severity = SafetySeverity.HIGH
        else:
            verdict = SafetyVerdict.REVIEW
            severity = SafetySeverity.MEDIUM

        result = PromptSafetyResult(
            verdict=verdict,
            injection_detected=True,
            matched_patterns=names,
            reasons=reasons,
            severity=severity,
        )
        _LOG.warning(
            "bridge.governance.prompt_injection_detected",
            verdict=verdict.value,
            patterns=list(names),
            severity=severity.value,
        )
        return result


# ---------------------------------------------------------------------------
# IntentClassifier
# ---------------------------------------------------------------------------


# Banking vocabulary that covers the three Bridge surfaces: chatbot
# (balances, statements), call center (general support), and smart
# payments (PIX, transfers). Stored in lowercase for case-insensitive
# substring matching.
_BANKING_TERMS: Final[frozenset[str]] = frozenset(
    {
        # English
        "account",
        "balance",
        "transfer",
        "deposit",
        "withdraw",
        "loan",
        "credit",
        "debit",
        "card",
        "statement",
        "interest",
        "investment",
        "savings",
        "bank",
        "payment",
        "pay",
        "transaction",
        "fee",
        "checking",
        "mortgage",
        "fraud",
        # Portuguese (BR)
        "conta",
        "saldo",
        "transferência",
        "transferencia",
        "depósito",
        "deposito",
        "saque",
        "empréstimo",
        "emprestimo",
        "crédito",
        "credito",
        "débito",
        "debito",
        "cartão",
        "cartao",
        "extrato",
        "juros",
        "investimento",
        "poupança",
        "poupanca",
        "banco",
        "boleto",
        "pix",
        "ted",
        "doc",
        "pagamento",
        "pagar",
        "transação",
        "transacao",
        "tarifa",
        "financiamento",
        "fatura",
        "limite",
        "chave pix",
        "consórcio",
        "consorcio",
        "seguro",
        "previdência",
        "previdencia",
        "agência",
        "agencia",
        "fraude",
    }
)

_OUT_OF_SCOPE_TERMS: Final[Mapping[ScopeDomain, frozenset[str]]] = {
    ScopeDomain.MEDICAL: frozenset(
        {
            "doctor",
            "medical",
            "medication",
            "diagnosis",
            "symptom",
            "médico",
            "medico",
            "medicamento",
            "remédio",
            "remedio",
            "diagnóstico",
            "diagnostico",
            "sintoma",
            "hospital",
        }
    ),
    ScopeDomain.LEGAL: frozenset(
        {
            "lawyer",
            "lawsuit",
            "legal advice",
            "court",
            "judge",
            "advogado",
            "processo judicial",
            "ação judicial",
            "tribunal",
            "juiz",
            "jurídico",
            "juridico",
        }
    ),
    ScopeDomain.POLITICAL: frozenset(
        {
            "election",
            "vote for",
            "political party",
            "candidate",
            "eleição",
            "eleicao",
            "vote em",
            "partido político",
            "partido politico",
            "candidato",
        }
    ),
}


class IntentClassifier:
    """Lightweight in-scope / out-of-scope classifier.

    The classifier is intentionally a transparent keyword matcher
    rather than a learned model. Three reasons:

    1. *Explainability for SR 11-7* — the matched terms are written
       into the audit trail, so a regulator can see *exactly* why a
       customer query was refused.
    2. *No silent drift* — adding a banking term is a code review,
       not a retraining event.
    3. *Latency floor* — runs in microseconds, leaving the whole
       latency budget for the actual LLM call.

    Parameters
    ----------
    banking_terms:
        Override or extend the default banking vocabulary. The default
        already covers Bradesco's three Bridge surfaces; supply this
        only when adding a new product surface (e.g., insurance).
    extra_out_of_scope:
        Mapping from a :class:`ScopeDomain` to additional out-of-scope
        terms. Merged with the built-in dictionaries.
    require_strong_banking:
        When ``True``, a query is considered in-scope *only* if it has
        at least one banking term. Defaults to ``False`` because the
        chatbot must gracefully handle short follow-ups like "yes" /
        "obrigado" that have no domain signal — those default to
        ``GENERIC`` but are treated as in-scope.
    """

    def __init__(
        self,
        *,
        banking_terms: Iterable[str] | None = None,
        extra_out_of_scope: Mapping[ScopeDomain, Iterable[str]] | None = None,
        require_strong_banking: bool = False,
    ) -> None:
        self._banking_terms: frozenset[str] = (
            frozenset(t.lower() for t in banking_terms)
            if banking_terms is not None
            else _BANKING_TERMS
        )
        merged: dict[ScopeDomain, frozenset[str]] = {
            domain: frozenset(vocab) for domain, vocab in _OUT_OF_SCOPE_TERMS.items()
        }
        if extra_out_of_scope:
            for domain, vocab in extra_out_of_scope.items():
                merged[domain] = merged.get(domain, frozenset()) | frozenset(
                    t.lower() for t in vocab
                )
        self._out_of_scope: Mapping[ScopeDomain, frozenset[str]] = merged
        self._require_strong_banking = bool(require_strong_banking)

    def classify_intent(self, query: str) -> IntentResult:
        """Return a structured :class:`IntentResult` for ``query``."""
        if not isinstance(query, str):
            raise GovernanceError(f"classify_intent requires a str, got {type(query).__name__}")

        cleaned = query.strip().lower()
        if not cleaned:
            return IntentResult(
                domain=ScopeDomain.UNKNOWN,
                in_scope=False,
                reasons=("empty query",),
            )

        banking_hits = [t for t in self._banking_terms if t in cleaned]

        oos_hits: dict[ScopeDomain, list[str]] = {}
        for domain, vocab in self._out_of_scope.items():
            hits = [t for t in vocab if t in cleaned]
            if hits:
                oos_hits[domain] = hits

        # If any out-of-scope domain has *more* matches than banking, the
        # query is treated as that domain. Ties go to banking — Bridge
        # would rather attempt a borderline financial answer than refuse
        # a legitimate banking customer.
        winning_oos: ScopeDomain | None = None
        winning_count = 0
        for domain, hits in oos_hits.items():
            if len(hits) > winning_count and len(hits) > len(banking_hits):
                winning_oos = domain
                winning_count = len(hits)

        if winning_oos is not None:
            return IntentResult(
                domain=winning_oos,
                in_scope=False,
                confidence=min(1.0, winning_count / 3.0),
                matched_terms=tuple(sorted(oos_hits[winning_oos])),
                reasons=(f"matched {winning_count} {winning_oos.value} term(s)",),
            )

        if banking_hits:
            return IntentResult(
                domain=ScopeDomain.BANKING,
                in_scope=True,
                confidence=min(1.0, len(banking_hits) / 3.0),
                matched_terms=tuple(sorted(banking_hits)),
                reasons=(f"matched {len(banking_hits)} banking term(s)",),
            )

        return IntentResult(
            domain=ScopeDomain.GENERIC,
            in_scope=not self._require_strong_banking,
            confidence=0.0,
            reasons=("no domain-specific terms matched",),
        )

    def validate_scope(self, query: str) -> bool:
        """Return ``True`` when ``query`` is in Bridge's banking scope.

        Thin convenience wrapper over :meth:`classify_intent` for
        callers that only need a yes/no answer.
        """
        return self.classify_intent(query).in_scope


# ---------------------------------------------------------------------------
# GovernancePipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GovernancePipeline:
    """Composite governance gate combining all three component checks.

    The pipeline is the entry point used by
    :class:`~lub.bridge.BridgePlatform`: :meth:`evaluate_request` runs
    input-side checks (prompt injection + scope) before model dispatch,
    and :meth:`evaluate_response` runs output-side content safety on
    the completion before it reaches the customer.

    Attributes
    ----------
    prompt_guard:
        Optional :class:`PromptGuard`; when ``None`` the pipeline skips
        prompt-injection checks (useful for trusted internal callers).
    content_filter:
        Optional :class:`ContentSafetyFilter`; when ``None`` the
        pipeline skips content-safety checks.
    intent_classifier:
        Optional :class:`IntentClassifier`; when ``None`` the pipeline
        accepts any topic. Bridge surfaces should leave this set.
    """

    prompt_guard: PromptGuard | None = None
    content_filter: ContentSafetyFilter | None = None
    intent_classifier: IntentClassifier | None = None

    def evaluate_request(self, prompt: str) -> GovernanceVerdict:
        """Run input-side governance: prompt injection + scope check."""
        reasons: list[str] = []
        prompt_safety: PromptSafetyResult | None = None
        intent: IntentResult | None = None

        if self.prompt_guard is not None:
            prompt_safety = self.prompt_guard.check_prompt(prompt)
            if not prompt_safety.safe:
                reasons.append(
                    f"prompt safety: {prompt_safety.verdict.value} "
                    f"({', '.join(prompt_safety.matched_patterns) or 'no pattern'})"
                )

        if self.intent_classifier is not None:
            intent = self.intent_classifier.classify_intent(prompt)
            if not intent.in_scope:
                reasons.append(f"out of scope: domain={intent.domain.value}")

        allowed = (prompt_safety is None or prompt_safety.safe) and (
            intent is None or intent.in_scope
        )

        verdict = GovernanceVerdict(
            allowed=allowed,
            prompt_safety=prompt_safety,
            intent=intent,
            reasons=tuple(reasons),
        )
        _LOG.info(
            "bridge.governance.request_evaluated",
            allowed=allowed,
            prompt_verdict=prompt_safety.verdict.value if prompt_safety else None,
            intent_domain=intent.domain.value if intent else None,
            in_scope=intent.in_scope if intent else None,
        )
        return verdict

    def evaluate_response(self, text: str) -> GovernanceVerdict:
        """Run output-side governance: content safety on model completion."""
        reasons: list[str] = []
        content: SafetyResult | None = None

        if self.content_filter is not None:
            content = self.content_filter.check_content(text)
            if not content.safe:
                reasons.append(
                    f"content safety: {content.verdict.value} "
                    f"({', '.join(c.value for c in content.categories) or 'no category'})"
                )

        allowed = content is None or content.safe
        verdict = GovernanceVerdict(
            allowed=allowed,
            content_safety=content,
            reasons=tuple(reasons),
        )
        _LOG.info(
            "bridge.governance.response_evaluated",
            allowed=allowed,
            content_verdict=content.verdict.value if content else None,
            categories=[c.value for c in content.categories] if content else [],
        )
        return verdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SEVERITY_ORDER: Final[tuple[SafetySeverity, ...]] = (
    SafetySeverity.NONE,
    SafetySeverity.LOW,
    SafetySeverity.MEDIUM,
    SafetySeverity.HIGH,
)


def _severity_rank(severity: SafetySeverity) -> int:
    try:
        return _SEVERITY_ORDER.index(severity)
    except ValueError:
        return 0


def _max_severity(a: SafetySeverity, b: SafetySeverity) -> SafetySeverity:
    return a if _severity_rank(a) >= _severity_rank(b) else b


def _worst_severity(values: Iterable[SafetySeverity]) -> SafetySeverity:
    worst = SafetySeverity.NONE
    for v in values:
        if _severity_rank(v) > _severity_rank(worst):
            worst = v
    return worst
