# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Complexity-based query routing for the Bridge platform.

Inspired by ``ruvnet/ruflo`` (MIT) and similar multi-LLM frameworks: the
cheapest model that can answer well IS the right model. Complex queries
get routed to expensive frontier models; simple lookups go to cheap fast
ones. This typically cuts inference cost 5-10x with negligible quality
loss on the easy queries — which are the bulk of banking traffic
(balance / fatura / chave PIX lookups).

This module sits *above* :class:`~lub.connectors.bridge.router.BridgeRouter`:
the complexity scorer assigns a tier; the router then picks among
backends matching that tier's :class:`~lub.connectors.bridge.router.RouteRequirements`.

Pipeline integration::

    query  ->  ComplexityRouter.score(query)         # this module
           ->  RouteRequirements(tier=tier)
           ->  BridgeRouter.route(requirements)      # bridge.router
           ->  backend.complete(query)

Why we don't just LLM-classify complexity: that adds a full inference
hop before the real one, doubling latency and cost on every query. The
heuristic scorer here uses a small handful of cheap signals (length,
question structure, multi-step markers, banking jargon density) that
correlate well with empirical model-quality requirements.

Banking notes
-------------

The tier mapping is conservative: when in doubt, escalate up. A wrong
tier-down classification (sent simple to a cheap model) costs goodwill;
a wrong tier-up (sent complex to expensive model) only costs money.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import structlog

__all__ = [
    "ComplexitySignals",
    "ComplexityScore",
    "ComplexityRouter",
    "ComplexityTier",
]

_LOG = structlog.get_logger("lub.bridge.complexity")


class ComplexityTier(StrEnum):
    """Coarse complexity tiers; map directly to backend cost tiers.

    ``SIMPLE``: lookup-style, single-fact questions. Cheap model fine.
    ``MEDIUM``: short reasoning, transactional flows (PIX validation,
    eligibility check). Mid-tier model.
    ``COMPLEX``: multi-step reasoning, ambiguous intent, regulatory
    explanations. Frontier model.
    """

    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


# ---------------------------------------------------------------------------
# Heuristic signals
# ---------------------------------------------------------------------------

# Tokens that mark multi-step reasoning ("first do X, then Y").
_MULTI_STEP_MARKERS: Final = (
    "primeiro",
    "depois",
    "entao",
    "em seguida",
    "first",
    "then",
    "afterwards",
    "step",
)

# Banking jargon that often signals complex regulatory questions.
_REGULATORY_JARGON: Final = (
    "bcb",
    "bacen",
    "bcbs",
    "basileia",
    "compliance",
    "lgpd",
    "kyc",
    "aml",
    "lavagem",
    "tributacao",
    "imposto",
    "irpf",
    "iof",
    "cdc",
    "cmn",
    "circular",
    "resolucao",
)

# Conditional / hypothetical markers ("se", "caso", "supondo").
_CONDITIONAL_MARKERS: Final = ("se ", "caso ", "supondo", "hipoteticamente", "what if", "suppose")

# Comparison markers ("melhor que", "vs", "comparado com").
_COMPARISON_MARKERS: Final = (
    " vs ",
    "versus",
    "comparado",
    "melhor que",
    "diferenca entre",
    "compare",
)

_SENTENCE_SPLIT = re.compile(r"[.!?]+")


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComplexitySignals:
    """All raw signals extracted from a query. Useful for audit/debug."""

    char_count: int
    word_count: int
    sentence_count: int
    question_count: int
    has_multi_step: bool
    has_regulatory_jargon: bool
    has_conditional: bool
    has_comparison: bool
    digit_density: float
    """Fraction of chars that are digits — high for transaction queries."""


@dataclass(frozen=True)
class ComplexityScore:
    """Output of :meth:`ComplexityRouter.score`.

    The ``tier`` is what the routing layer cares about; ``signals`` and
    ``rationale`` exist for the audit trail (BCB 4893 reviewers ask
    *why* a query was routed to a particular model).
    """

    tier: ComplexityTier
    raw_score: float
    signals: ComplexitySignals
    rationale: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


@dataclass
class ComplexityRouter:
    """Heuristic complexity scorer + tier mapper.

    Thresholds are tunable so a deployment can re-calibrate against its
    own traffic without forking the module. Defaults are calibrated for
    Brazilian banking traffic where the median query is a balance /
    fatura check.
    """

    simple_threshold: float = 1.0
    medium_threshold: float = 3.0

    def __post_init__(self) -> None:
        if self.simple_threshold >= self.medium_threshold:
            raise ValueError(
                "simple_threshold must be < medium_threshold "
                f"(got simple={self.simple_threshold}, medium={self.medium_threshold})"
            )

    def extract_signals(self, query: str) -> ComplexitySignals:
        """Pure extraction; no scoring decisions."""
        normalized = query.lower()
        words = query.split()
        sentences = [s for s in _SENTENCE_SPLIT.split(query) if s.strip()]
        digits = sum(1 for c in query if c.isdigit())

        return ComplexitySignals(
            char_count=len(query),
            word_count=len(words),
            sentence_count=len(sentences),
            question_count=query.count("?"),
            has_multi_step=any(m in normalized for m in _MULTI_STEP_MARKERS),
            has_regulatory_jargon=any(m in normalized for m in _REGULATORY_JARGON),
            has_conditional=any(m in normalized for m in _CONDITIONAL_MARKERS),
            has_comparison=any(m in normalized for m in _COMPARISON_MARKERS),
            digit_density=digits / max(len(query), 1),
        )

    def compute_raw_score(self, signals: ComplexitySignals) -> float:
        """Map signals to a raw complexity score (higher = more complex).

        Each signal contributes additively. Weights are deliberately
        small integers so the score is easy to reason about.
        """
        score = 0.0

        # Length: longer queries tend to be more complex.
        if signals.word_count > 30:
            score += 2.0
        elif signals.word_count > 15:
            score += 1.0
        elif signals.word_count > 5:
            score += 0.5

        # Multiple sentences => multiple subtopics.
        if signals.sentence_count > 2:
            score += 1.5
        elif signals.sentence_count == 2:
            score += 0.5

        # Multiple questions => multi-part query.
        if signals.question_count > 1:
            score += 1.0

        # Strong complexity markers.
        if signals.has_multi_step:
            score += 1.5
        if signals.has_regulatory_jargon:
            score += 3.0  # regulatory always escalates to COMPLEX tier
        if signals.has_conditional:
            score += 1.0
        if signals.has_comparison:
            score += 1.0

        return score

    def map_to_tier(self, raw_score: float) -> ComplexityTier:
        """Apply thresholds. Conservative: ties round up."""
        if raw_score < self.simple_threshold:
            return ComplexityTier.SIMPLE
        if raw_score < self.medium_threshold:
            return ComplexityTier.MEDIUM
        return ComplexityTier.COMPLEX

    def score(self, query: str) -> ComplexityScore:
        """Full pipeline: extract signals -> raw score -> tier -> audit string."""
        signals = self.extract_signals(query)
        raw = self.compute_raw_score(signals)
        tier = self.map_to_tier(raw)

        rationale_parts: list[str] = [f"raw={raw:.1f}"]
        if signals.word_count > 30:
            rationale_parts.append("long")
        if signals.has_multi_step:
            rationale_parts.append("multi-step")
        if signals.has_regulatory_jargon:
            rationale_parts.append("regulatory")
        if signals.has_conditional:
            rationale_parts.append("conditional")
        if signals.has_comparison:
            rationale_parts.append("comparison")
        if signals.question_count > 1:
            rationale_parts.append(f"{signals.question_count} questions")
        rationale = ", ".join(rationale_parts)

        _LOG.info(
            "bridge.complexity.scored",
            tier=tier.value,
            raw_score=raw,
            word_count=signals.word_count,
            rationale=rationale,
        )

        return ComplexityScore(
            tier=tier,
            raw_score=raw,
            signals=signals,
            rationale=rationale,
        )
