# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Grounding-aware uncertainty signal — bridges RAG output to the Guard.

This module closes the weakest connection in the Bridge pipeline:
between stage 4 (:mod:`~lub.connectors.bridge.rag` retrieval) and stage 7
(:class:`~lub.guard.UncertaintyGuard`). Today the RAG pipeline produces
:class:`~lub.connectors.bridge.rag.RAGResult` with grounding evidence and
citation labels, the agent (stage 6) consumes them inside the grounded
prompt, but the guard never sees them — it scores the *prompt* against
its own pipeline, blind to whether the agent's answer is faithful to the
retrieved evidence.

For a Bradesco production deployment under BCB 4893, an ungrounded
hallucination delivered with high LLM-side confidence is the single
worst failure mode: the answer is plausible, the guard PASSES it, and
the audit log captures a confident but unsupported statement. This
module produces a per-answer faithfulness score and exposes a single
helper, :func:`combine_with_guard`, that downgrades the guard verdict
when grounding is weak — preserving Bridge's "guard gates, does not
substitute" contract.

Three signals make up :class:`GroundingScore`:

* **citation_score** — does the answer cite at least one of the sources
  in :attr:`RAGResult.citations`, via the ``[Fonte: ...]`` marker
  enforced by the prompt template in :mod:`~lub.connectors.bridge.rag`?
  Partial credit when only some retrieved sources are acknowledged.
* **support_score** — fraction of the answer's content tokens that
  also appear in the union of retrieved doc texts. Tokens absent from
  retrieved evidence are treated as potentially unsupported. Portuguese
  stopwords are stripped first so common function words don't inflate
  the score.
* **coverage_score** — does the retrieval itself look usable
  (``RAGResult.has_grounding`` is True and the top retrieved similarity
  cleared ``min_top_score``)? When False, even a verbatim citation is a
  false-positive and the overall score is forced low.

The combined :attr:`GroundingScore.confidence` is the geometric mean of
those three components, which preserves the "any zero kills it"
intuition that matters most for regulated answers — a single missing
dimension cannot be averaged away by the other two.

The module is intentionally cost-conscious: pure Python, no
transformers, no external NLI model. It is meant for cheap
pre-filtering. Deployments that need strict NLI-grade faithfulness can
slot in a model-based evaluator by implementing
:class:`GroundingEvaluator`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Protocol, runtime_checkable

import structlog

from lub.connectors.bridge.rag import RAGResult
from lub.guard import GuardResult, PolicyDecision
from lub.policies import PolicyOutcome

__all__ = [
    "GroundingEvaluator",
    "GroundingScore",
    "LexicalGroundingEvaluator",
    "combine_with_guard",
]

_LOG = structlog.get_logger("lub.bridge.grounding")

# PT-BR aware: keep accented characters so "fluxo de caixa" survives
# tokenization. Three-char minimum mirrors :mod:`~lub.connectors.bridge.rag`.
_TOKEN_RE: Final = re.compile(r"[a-z0-9\u00c0-\u017f]{3,}")

# Matches the citation marker enforced by the prompt template in rag.py:
# "[Fonte: <source>]". Case-insensitive because LLMs frequently lowercase
# the keyword and we never want to penalize that.
_CITATION_RE: Final = re.compile(r"\[fonte:\s*([^\]]+)\]", re.IGNORECASE)

# Minimal PT-BR banking stopword set. Kept short on purpose: false negatives
# (a non-stopword we treat as content) bias support_score downward, which is
# the safe direction for a faithfulness check. We do not import a full NLTK
# stopword list — that's a dep we don't need and would mask under-grounding.
_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "para",
        "como",
        "isso",
        "esse",
        "essa",
        "este",
        "esta",
        "pelo",
        "pela",
        "dos",
        "das",
        "uma",
        "uns",
        "umas",
        "que",
        "com",
        "por",
        "mas",
        "nao",
        "sim",
        "voce",
        "voces",
        "ser",
        "tem",
        "fui",
        "foi",
        "sao",
        "the",
        "and",
        "for",
        "with",
    }
)


# ---------------------------------------------------------------------------
# Public dataclasses + protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroundingScore:
    """Per-answer faithfulness signal computed against a :class:`RAGResult`.

    Attributes
    ----------
    citation_score:
        ``[0, 1]``. 1.0 when the answer cites every retrieved source,
        an intermediate value (>= ``partial_citation_credit``) when at
        least one valid citation is present, and 0.0 when no marker is
        emitted or every marker points to a source absent from
        ``RAGResult.citations`` (the "fabricated citation" case).
    support_score:
        ``[0, 1]``. Fraction of the answer's content tokens that also
        appear in the union of retrieved doc texts. A low value means
        the answer is mostly novel material not backed by evidence.
    coverage_score:
        ``[0, 1]``. Quality of the retrieval itself — 1.0 when
        ``rag.has_grounding`` and the top doc's similarity is above
        ``min_top_score``; decays linearly to 0 as the top score falls.
    cited_sources:
        The raw ``[Fonte: ...]`` strings observed in the answer, in
        order of first appearance, for audit traceability.
    missing_sources:
        Sources present in ``RAGResult.citations`` but never cited by
        the answer. A non-empty value flags a partially-grounded
        answer to the compliance reviewer.
    unsupported_token_ratio:
        ``[0, 1]``. ``1.0 - support_score`` cached for convenience so
        audit consumers don't have to recompute it.
    """

    citation_score: float
    support_score: float
    coverage_score: float
    cited_sources: tuple[str, ...]
    missing_sources: tuple[str, ...]
    unsupported_token_ratio: float

    @property
    def confidence(self) -> float:
        """Geometric-mean blend in ``[0, 1]``.

        Geometric mean is deliberate: if any single dimension is zero
        (no citation, or no support, or no coverage), the answer is
        unfit for a regulated channel and the combined confidence
        collapses to zero. An arithmetic mean would average a zero
        away — exactly the failure mode this signal exists to prevent.
        """
        parts = (self.citation_score, self.support_score, self.coverage_score)
        clamped = [max(min(float(p), 1.0), 0.0) for p in parts]
        product = 1.0
        for p in clamped:
            product *= p
        if product <= 0.0:
            return 0.0
        return product ** (1.0 / len(clamped))  # type: ignore[no-any-return]

    def as_audit(self) -> dict[str, Any]:
        """Flat, JSON-serializable dict for the BCB 4893 audit envelope."""
        return {
            "citation_score": float(self.citation_score),
            "support_score": float(self.support_score),
            "coverage_score": float(self.coverage_score),
            "unsupported_token_ratio": float(self.unsupported_token_ratio),
            "confidence": float(self.confidence),
            "cited_sources": list(self.cited_sources),
            "missing_sources": list(self.missing_sources),
        }


@runtime_checkable
class GroundingEvaluator(Protocol):
    """Pluggable answer-vs-evidence scorer.

    The default :class:`LexicalGroundingEvaluator` is lexical and free;
    production deployments that need higher fidelity can swap in a
    transformer-NLI evaluator that implements the same ``score`` method
    without changing :class:`~lub.connectors.bridge.platform.BridgePlatform`.
    """

    def score(self, answer: str, rag: RAGResult) -> GroundingScore:
        """Score ``answer`` against ``rag`` and return a :class:`GroundingScore`."""
        ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Lowercase tokenize with PT-BR stopword removal."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


# ---------------------------------------------------------------------------
# Lexical evaluator
# ---------------------------------------------------------------------------


@dataclass
class LexicalGroundingEvaluator:
    """Lexical, cost-zero grounding scorer.

    Three signals, all pure Python (no transformers, no external NLI):

    * **citation_score**: parse ``[Fonte: ...]`` markers and compare to
      :attr:`RAGResult.citations`. Full credit when every retrieved
      source is cited, ``partial_citation_credit`` (or higher) when at
      least one valid source is acknowledged, zero when the answer
      omits markers entirely or invents a source not in the retrieval
      set (the "fabricated citation" case is the worst — it can fool
      a downstream string-match regex check).
    * **support_score**: token-overlap between the answer and the
      union of retrieved doc texts. Stopwords are stripped first.
    * **coverage_score**: 1.0 when ``rag.has_grounding`` and the top
      retrieved score is at least ``min_top_score``; linearly decays
      to 0 below that.

    Parameters
    ----------
    min_top_score:
        Top retrieved-doc similarity below which ``coverage_score``
        starts to decay. Defaults to 0.10, slightly above
        :attr:`~lub.connectors.bridge.rag.RAGPipeline.min_score` so the
        gate fires earlier than the pipeline's hard cutoff.
    partial_citation_credit:
        Score awarded when the answer cites *some* retrieved sources
        but not all. Set to 0.0 for "all-or-nothing" semantics; the
        default 0.5 acknowledges partial grounding without giving it a
        passing grade outright.
    """

    min_top_score: float = 0.10
    partial_citation_credit: float = 0.5

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_top_score <= 1.0:
            raise ValueError(f"min_top_score must be in [0, 1] (got {self.min_top_score})")
        if not 0.0 <= self.partial_citation_credit <= 1.0:
            raise ValueError(
                f"partial_citation_credit must be in [0, 1] (got {self.partial_citation_credit})"
            )

    def score(self, answer: str, rag: RAGResult) -> GroundingScore:
        """Compute the three signals against ``rag`` and combine them."""
        coverage = self._score_coverage(rag)
        citation, cited, missing = self._score_citations(answer, rag)
        support, unsupported_ratio = self._score_support(answer, rag)

        result = GroundingScore(
            citation_score=citation,
            support_score=support,
            coverage_score=coverage,
            cited_sources=cited,
            missing_sources=missing,
            unsupported_token_ratio=unsupported_ratio,
        )
        _LOG.info(
            "bridge.grounding.scored",
            citation=round(citation, 3),
            support=round(support, 3),
            coverage=round(coverage, 3),
            confidence=round(result.confidence, 3),
            retrieved=len(rag.retrieved),
        )
        return result

    def _score_coverage(self, rag: RAGResult) -> float:
        if not rag.has_grounding:
            return 0.0
        top = float(rag.retrieved[0].score)
        if top >= self.min_top_score:
            return 1.0
        return max(0.0, top / self.min_top_score) if self.min_top_score > 0 else 0.0

    def _score_citations(
        self,
        answer: str,
        rag: RAGResult,
    ) -> tuple[float, tuple[str, ...], tuple[str, ...]]:
        cited_raw = tuple(m.group(1).strip() for m in _CITATION_RE.finditer(answer))
        cited_norm = {c.lower() for c in cited_raw}
        retrieved_norm = {c.lower() for c in rag.citations}

        if not retrieved_norm:
            # Nothing was retrieved, so we can't fairly judge citations.
            # Coverage will already be 0 in this branch — citation_score
            # is moot under the geometric-mean combiner.
            return 0.0, cited_raw, tuple(cited_raw)

        if not cited_norm:
            return 0.0, cited_raw, tuple(rag.citations)

        valid = cited_norm & retrieved_norm
        if not valid:
            # The answer cites something, but none of it matches retrieved.
            # That's a fabricated source — strictly worse than no citation,
            # but the geometric mean already zeroes the contribution.
            return 0.0, cited_raw, tuple(rag.citations)

        if valid >= retrieved_norm:
            citation = 1.0
        else:
            matched_ratio = len(valid) / len(retrieved_norm)
            citation = (
                self.partial_citation_credit + (1.0 - self.partial_citation_credit) * matched_ratio
            )

        missing = tuple(src for src in rag.citations if src.lower() not in cited_norm)
        return citation, cited_raw, missing

    def _score_support(self, answer: str, rag: RAGResult) -> tuple[float, float]:
        answer_tokens = _tokenize(answer)
        if not answer_tokens:
            return 0.0, 0.0
        if not rag.has_grounding:
            return 0.0, 1.0

        evidence: set[str] = set()
        for retrieved in rag.retrieved:
            evidence.update(_tokenize(retrieved.document.text))
        if not evidence:
            return 0.0, 1.0

        supported = sum(1 for tok in answer_tokens if tok in evidence)
        support = supported / len(answer_tokens)
        return support, 1.0 - support


# ---------------------------------------------------------------------------
# Combiner — the actual bridge between RAG and the Guard
# ---------------------------------------------------------------------------


def combine_with_guard(
    verdict: GuardResult,
    grounding: GroundingScore,
    *,
    hard_floor: float = 0.20,
    soft_floor: float = 0.50,
    abstain_marker: str | None = None,
) -> GuardResult:
    """Downgrade ``verdict`` when ``grounding`` is weak.

    This is the actual bridge between Bridge's stage-4 RAG and stage-7
    guard. The guard's own confidence stays in ``verdict.outcome.confidence``
    — we never overwrite it. Instead we *downgrade the decision* when
    the grounding signal disagrees with the guard's optimistic verdict,
    and we attach the full :class:`GroundingScore` to the policy
    metadata so BCB 4893 reviewers can see both signals side-by-side.

    Parameters
    ----------
    verdict:
        Original :class:`GuardResult` produced by Bridge's stage-7 guard.
    grounding:
        Faithfulness score from :meth:`GroundingEvaluator.score`.
    hard_floor:
        Below this the policy is forced to :attr:`PolicyDecision.ABSTAIN`
        regardless of the guard's own confidence.
    soft_floor:
        Below this (but above ``hard_floor``) the policy is forced to
        :attr:`PolicyDecision.FLAG` — the answer still ships but is
        marked for human review.
    abstain_marker:
        Text to surface in :attr:`GuardResult.output` on ABSTAIN. When
        ``None`` the original guard's output is preserved (callers that
        need a custom abstain message should pass an explicit marker).

    Returns
    -------
    GuardResult
        Either the original verdict (when grounding is acceptable) or a
        new :class:`GuardResult` with a downgraded decision and a
        ``grounding`` block merged into the metadata. The agent's
        answer text is preserved: this is a *gating* operation, not a
        substitution — same contract as
        :class:`~lub.connectors.bridge.platform.BridgePlatform`.

    Raises
    ------
    ValueError
        If ``hard_floor`` > ``soft_floor`` or either falls outside
        ``[0, 1]``.
    """
    if not 0.0 <= hard_floor <= 1.0:
        raise ValueError(f"hard_floor must be in [0, 1] (got {hard_floor})")
    if not 0.0 <= soft_floor <= 1.0:
        raise ValueError(f"soft_floor must be in [0, 1] (got {soft_floor})")
    if hard_floor > soft_floor:
        raise ValueError(f"hard_floor ({hard_floor}) must be <= soft_floor ({soft_floor})")

    confidence = grounding.confidence
    if confidence >= soft_floor:
        return verdict

    if confidence < hard_floor:
        new_decision = PolicyDecision.ABSTAIN
        passed = False
        reason = (
            f"grounding<{hard_floor:.2f} (got {confidence:.3f}); answer suppressed for human review"
        )
        output = abstain_marker if abstain_marker is not None else verdict.output
    else:
        new_decision = PolicyDecision.FLAG
        passed = bool(verdict.outcome.passed)
        reason = f"grounding<{soft_floor:.2f} (got {confidence:.3f}); answer released with FLAG"
        output = verdict.output

    merged_meta: dict[str, Any] = dict(verdict.outcome.metadata)
    merged_meta["grounding"] = grounding.as_audit()
    merged_meta["grounding_downgrade"] = reason
    merged_meta["grounding_prior_decision"] = verdict.outcome.decision.value

    new_outcome = PolicyOutcome(
        decision=new_decision,
        confidence=float(verdict.outcome.confidence),
        threshold=float(verdict.outcome.threshold),
        passed=passed,
        answer=verdict.outcome.answer,
        reason=reason,
        metadata=merged_meta,
    )
    _LOG.warning(
        "bridge.grounding.downgrade",
        from_decision=verdict.outcome.decision.value,
        to_decision=new_decision.value,
        grounding_confidence=round(confidence, 3),
        guard_confidence=round(float(verdict.outcome.confidence), 3),
    )
    return GuardResult(
        raw=verdict.raw,
        outcome=new_outcome,
        output=output,
        rmf_subcategory=verdict.rmf_subcategory,
    )
