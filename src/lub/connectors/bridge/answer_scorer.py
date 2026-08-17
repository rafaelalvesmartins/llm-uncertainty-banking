# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Post-hoc rescoring of agent answers — closing the Bridge↔LUB calibration gap.

Bridge's :class:`~lub.guard.UncertaintyGuard` gates the registered agent's
answer using a confidence score that was computed for the **guard
pipeline's own answer**, not the agent's. When the two diverge — which is
the rule, not the exception, once the agent gains retrieval, tools, or
domain fine-tuning that the guard's pipeline does not share — every
release becomes an uncalibrated decision: we are using calibration for
text B to gate the release of text A.

:mod:`lub.connectors.bridge.platform` already emits a
``query.answer_divergence`` audit event when A ≠ B and acknowledges the
gap as a known limitation. This module closes it by re-attributing
confidence to the **agent's actual answer**. Each :class:`AnswerScorer`
accepts ``(prompt, answer)`` and returns an
:class:`~lub.types.UncertaintyResult` whose confidence is a function of
the agent's answer text itself — not of any parallel completion.

Three pure-Python scorers are provided, all cost-conscious so the
post-hoc step does not blow up Bridge's latency budget:

* :class:`LexicalConsistencyScorer` — re-samples the agent (or a
  cheaper backup) and measures Jaccard token agreement with the
  agent's answer. Deterministic, no external dependency beyond the
  sampler callable.
* :class:`PTrueScorer` — asks a verifier callable "is this answer
  correct?" and parses the natural-language reply into a probability.
* :class:`CompositeAnswerScorer` — weighted geometric mean across
  scorers, with each contribution preserved in ``diagnostics`` for the
  AI RMF reporter.

:func:`gate_answer_score` wraps the resulting score in a
:class:`~lub.guard.GuardResult` so the Bridge platform can route it
through the same audit, OTEL, and RMF consumers as the existing guard.
The policy ladder here is intentionally minimal (PASSTHROUGH / ABSTAIN
around a threshold) — the rich REASK / FLAG / RAISE machinery lives in
:class:`~lub.guard.UncertaintyGuard`; this helper exists to *replace* the
miscalibrated verdict, not to duplicate the policy ladder.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import structlog

from lub.guard import GuardResult, PolicyDecision, rmf_subcategory
from lub.policies import PolicyOutcome
from lub.types import UncertaintyResult

__all__ = [
    "AnswerScorer",
    "CompositeAnswerScorer",
    "LexicalConsistencyScorer",
    "PTrueScorer",
    "gate_answer_score",
]

_LOG = structlog.get_logger("lub.bridge.answer_scorer")

_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)

DEFAULT_ABSTAIN_MARKER = "[ABSTAIN: answer-attributed confidence below threshold]"


def _tokenize(text: str) -> set[str]:
    """Case-folded word-token set for cheap lexical comparison."""
    return {m.group(0).casefold() for m in _TOKEN_PATTERN.finditer(text)}


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity with empty-set safety."""
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


@runtime_checkable
class AnswerScorer(Protocol):
    """Re-score an already-produced ``answer`` against its ``prompt``.

    Implementations MUST return an :class:`UncertaintyResult` whose
    ``answer`` field equals the passed-in ``answer`` (no substitution)
    and whose ``confidence`` is a function of that text. This is the
    contract that makes the score *attributable to the agent's actual
    answer*, which is the whole point of post-hoc rescoring.
    """

    def score(self, prompt: str, answer: str) -> UncertaintyResult:
        """Re-attribute confidence to the agent's released ``answer`` for Bridge to gate on.

        Bridge invokes implementations between stage 6 (Agent) and
        stage 7 (UncertaintyGuard) so the verdict that drives
        PASSTHROUGH / FLAG / REASK / ESCALATE is computed against the
        text the customer would actually receive — not the guard
        pipeline's parallel completion.

        Args:
            prompt: The customer-facing question the agent answered.
            answer: The agent's released text whose confidence is being
                re-attributed.

        Returns:
            An :class:`UncertaintyResult` with ``answer`` echoed
            verbatim and ``confidence`` derived from that text.
        """
        ...


# ---------------------------------------------------------------------------
# Lexical self-consistency
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LexicalConsistencyScorer:
    """Self-consistency rescorer using Jaccard token agreement.

    Re-samples ``sampler`` ``n_samples`` times and measures token overlap
    between each sample and the agent's *actual* answer. The mean
    Jaccard similarity is the confidence — high agreement means the
    answer is reproducible by the sampler, which is a calibrated signal
    for that exact text. The sampler may be the agent itself (with a
    non-zero temperature) for a true self-consistency check, or a
    cheaper backup model for a cross-model agreement check.

    Parameters
    ----------
    sampler:
        Callable ``(prompt) -> str`` used to draw alternate samples.
    n_samples:
        Number of resamples; must be >= 1. Higher values give a more
        stable confidence at proportionally higher cost. The default of
        5 is a tested compromise for banking Q&A latency budgets.
    """

    sampler: Callable[[str], str]
    n_samples: int = 5

    def __post_init__(self) -> None:
        if self.n_samples < 1:
            raise ValueError(f"n_samples must be >= 1, got {self.n_samples}")

    def score(self, prompt: str, answer: str) -> UncertaintyResult:
        """Return mean Jaccard agreement so Bridge gates on the agent's actual answer.

        Bridge wires this between its Agent stage and its
        UncertaintyGuard stage: the sampler is typically the same
        ComplexityRouter-selected LLM tier the agent used (re-sampled
        at a non-zero temperature), or a cheaper backup tier when the
        cost/QPS budget demands it. Sampler exceptions are swallowed
        and counted so a partial LLM-backend outage degrades gracefully
        into a lower confidence rather than a Bridge-wide failure.

        Args:
            prompt: The customer-facing question routed to the agent.
            answer: The agent's released text whose reproducibility is
                being measured.

        Returns:
            An :class:`UncertaintyResult` whose confidence is the mean
            Jaccard similarity between ``answer`` and each successful
            resample; ``should_refuse`` is set when every resample
            failed, signalling Bridge to escalate.
        """
        answer_tokens = _tokenize(answer)
        agreements: list[float] = []
        samples: list[str] = []
        n_errors = 0
        for _ in range(self.n_samples):
            try:
                sample = self.sampler(prompt)
            except Exception as exc:  # noqa: BLE001 — sampler may wrap external services
                n_errors += 1
                _LOG.warning(
                    "answer_scorer.lexical_consistency.sample_error",
                    error_type=type(exc).__name__,
                )
                continue
            samples.append(sample)
            agreements.append(_jaccard(answer_tokens, _tokenize(sample)))

        confidence = float(sum(agreements) / len(agreements)) if agreements else 0.0
        return UncertaintyResult(
            answer=answer,
            confidence=confidence,
            raw_scores={
                "lexical_jaccard_mean": confidence,
                "n_samples_succeeded": float(len(agreements)),
                "n_samples_failed": float(n_errors),
            },
            samples=samples or None,
            should_refuse=not agreements,
            diagnostics={"n_samples_requested": self.n_samples},
        )


# ---------------------------------------------------------------------------
# P(True) verifier
# ---------------------------------------------------------------------------


_TRUE_TOKENS: tuple[str, ...] = (
    "yes",
    "true",
    "correct",
    "right",
    "sim",
    "verdadeiro",
    "correto",
)
_FALSE_TOKENS: tuple[str, ...] = (
    "no",
    "false",
    "incorrect",
    "wrong",
    "não",
    "nao",
    "falso",
    "errado",
    "incorreto",
)


def _parse_p_true(verifier_response: str) -> float:
    """Map a verifier's natural-language reply to a probability in [0, 1].

    Uses keyword voting in English and Portuguese — Bradesco serves a
    Brazilian customer base so monolingual English parsing would lose
    most of the production signal. An ambiguous reply (no keywords
    on either side) returns 0.5 so it is treated as maximally
    uncertain rather than silently passing.
    """
    text = verifier_response.casefold()
    n_true = sum(1 for tok in _TRUE_TOKENS if tok in text)
    n_false = sum(1 for tok in _FALSE_TOKENS if tok in text)
    total = n_true + n_false
    if total == 0:
        return 0.5
    return n_true / total


DEFAULT_VERIFIER_TEMPLATE = (
    "You are a careful Bradesco banking quality reviewer.\n"
    "\n"
    "Customer question:\n{prompt}\n"
    "\n"
    "Proposed answer:\n{answer}\n"
    "\n"
    "Is the proposed answer correct, complete, free of hallucinated "
    "rates / fees / regulations, and safe to release to the customer? "
    "Reply with a single word: 'yes' or 'no'."
)


@dataclass(frozen=True)
class PTrueScorer:
    """LLM-judge rescorer (p_true variant) attributable to the agent's text.

    Asks ``verifier`` whether the agent's answer is correct given the
    prompt. The verifier's reply is parsed into a probability so the
    confidence is provably attributable to the **agent's actual answer
    text**, not to any parallel completion. The verifier should be a
    different model than the agent when possible — using the same model
    as judge and answerer is known to over-confidently affirm.

    Parameters
    ----------
    verifier:
        Callable ``(prompt) -> str``. Receives the formatted judgment
        prompt and returns a short natural-language reply (e.g.
        ``"yes"``, ``"no, the rate is wrong"``).
    template:
        Format string with ``{prompt}`` and ``{answer}`` placeholders.
        The default Portuguese/English template is tuned for Bradesco
        banking review and asks for a one-word reply to keep parsing
        deterministic.
    """

    verifier: Callable[[str], str]
    template: str = DEFAULT_VERIFIER_TEMPLATE

    def score(self, prompt: str, answer: str) -> UncertaintyResult:
        """Ask the verifier "is this correct?" and return P(true) for Bridge to gate on.

        Bridge typically wires ``verifier`` to a tier *different* from
        the one the ComplexityRouter selected for the agent — using the
        same model as both answerer and judge is known to
        over-confidently affirm, which would defeat the whole purpose
        of closing the divergence gap. A verifier exception returns
        ``confidence=0.0`` and ``should_refuse=True`` so Bridge
        escalates rather than passing through on a missing judgment.

        Args:
            prompt: The customer-facing question the agent answered.
            answer: The agent's released text being judged.

        Returns:
            An :class:`UncertaintyResult` whose confidence is the
            parsed probability that the verifier judged the answer
            correct; the raw reply is preserved in ``diagnostics`` for
            Bridge's BCB 4893 audit trail.
        """
        judgment_prompt = self.template.format(prompt=prompt, answer=answer)
        try:
            reply = self.verifier(judgment_prompt)
        except Exception as exc:  # noqa: BLE001 — verifier may wrap external services
            _LOG.error(
                "answer_scorer.p_true.verifier_error",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return UncertaintyResult(
                answer=answer,
                confidence=0.0,
                raw_scores={"p_true_probability": 0.0, "p_true_error": 1.0},
                diagnostics={
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                should_refuse=True,
            )
        probability = _parse_p_true(reply)
        return UncertaintyResult(
            answer=answer,
            confidence=probability,
            raw_scores={"p_true_probability": probability},
            diagnostics={"verifier_reply": reply},
        )


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompositeAnswerScorer:
    """Weighted geometric mean across multiple :class:`AnswerScorer` s.

    Geometric mean is the right aggregator for regulated gating: if any
    scorer returns zero confidence the composite returns zero, matching
    the regulator's expectation that every independent signal must
    clear the bar. An arithmetic mean would let a high lexical score
    mask a low p_true verdict — undesirable when the verdict is what
    a human reviewer would have raised.

    Parameters
    ----------
    weighted_scorers:
        Sequence of ``(scorer, weight)`` pairs. Weights must be > 0
        and are normalized to sum to 1 before aggregation. The order
        is preserved in ``diagnostics`` so the AI RMF reporter can
        cite each scorer by index.
    """

    weighted_scorers: tuple[tuple[AnswerScorer, float], ...]

    def __post_init__(self) -> None:
        if not self.weighted_scorers:
            raise ValueError("CompositeAnswerScorer requires at least one scorer")
        for _, w in self.weighted_scorers:
            if w <= 0:
                raise ValueError(f"weights must be positive, got {w}")

    def score(self, prompt: str, answer: str) -> UncertaintyResult:
        """Aggregate sub-scores via weighted geometric mean for Bridge's regulated gate.

        Bridge mounts a composite when more than one signal is required
        by policy (e.g. BCB 4893 high-risk flows demanding both
        self-consistency *and* an independent judge). The geometric
        mean ensures any sub-scorer returning zero collapses the
        composite to zero — matching the regulator's expectation that
        every independent signal must clear the bar — while each
        per-scorer contribution is preserved in ``diagnostics`` for the
        AI RMF reporter wired into Bridge's monitoring stage.
        ``should_refuse`` is OR'd across components so a single
        scorer's escalation signal propagates to Bridge intact.

        Args:
            prompt: The customer-facing question the agent answered.
            answer: The agent's released text being re-scored.

        Returns:
            An :class:`UncertaintyResult` whose confidence is the
            weighted geometric mean of sub-scorer confidences, clamped
            to ``[0, 1]``, with per-component evidence preserved in
            ``diagnostics`` and namespaced raw scores in
            ``raw_scores``.
        """
        total_weight = sum(w for _, w in self.weighted_scorers)
        components: list[dict[str, Any]] = []
        raw_scores: dict[str, float] = {}
        log_sum = 0.0
        any_refuse = False
        for idx, (scorer, weight) in enumerate(self.weighted_scorers):
            sub = scorer.score(prompt, answer)
            norm_weight = weight / total_weight
            clamped = max(sub.confidence, 1e-9)
            log_sum += norm_weight * math.log(clamped)
            any_refuse = any_refuse or sub.should_refuse
            scorer_tag = type(scorer).__name__.lower()
            components.append(
                {
                    "scorer_index": idx,
                    "scorer_type": type(scorer).__name__,
                    "weight": norm_weight,
                    "confidence": float(sub.confidence),
                    "should_refuse": bool(sub.should_refuse),
                }
            )
            for key, val in sub.raw_scores.items():
                raw_scores[f"{scorer_tag}.{key}"] = float(val)

        composite = math.exp(log_sum)
        composite = min(1.0, max(0.0, composite))
        raw_scores["composite_geometric"] = composite
        return UncertaintyResult(
            answer=answer,
            confidence=composite,
            raw_scores=raw_scores,
            should_refuse=any_refuse,
            diagnostics={"components": components},
        )


# ---------------------------------------------------------------------------
# Gate helper
# ---------------------------------------------------------------------------


def gate_answer_score(
    result: UncertaintyResult,
    threshold: float,
    abstain_marker: str = DEFAULT_ABSTAIN_MARKER,
) -> GuardResult:
    """Wrap an answer-attributed score in a :class:`GuardResult` envelope.

    Lets the Bridge platform feed a post-hoc score into the same
    audit / OTEL / RMF pipeline that the existing
    :class:`~lub.guard.UncertaintyGuard` uses. The policy here is
    intentionally simple — PASSTHROUGH at or above ``threshold``,
    ABSTAIN otherwise — because the rich REASK / FLAG / RAISE machinery
    already lives in :class:`UncertaintyGuard`. This helper exists to
    *replace* a miscalibrated guard verdict, not to duplicate the
    guard's policy ladder.

    Parameters
    ----------
    result:
        Output of any :class:`AnswerScorer` — its ``answer`` field is
        assumed to be the agent's released text (the whole point of
        this module).
    threshold:
        Decision boundary in ``[0, 1]``. Confidence at or above releases
        the answer; below abstains.
    abstain_marker:
        String returned in ``output`` when the gate abstains. Defaults
        to a distinct marker so an audit reader can tell this gate
        fired (as opposed to the upstream guard).

    Raises
    ------
    ValueError
        If ``threshold`` is outside ``[0, 1]``.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be in [0, 1], got {threshold}")
    passed = (result.confidence >= threshold) and not result.should_refuse
    decision = PolicyDecision.PASSTHROUGH if passed else PolicyDecision.ABSTAIN
    outcome = PolicyOutcome(
        decision=decision,
        confidence=float(result.confidence),
        threshold=float(threshold),
        passed=bool(passed),
        answer=result.answer,
        reason=(
            "answer-attributed confidence met threshold"
            if passed
            else "answer-attributed confidence below threshold"
        ),
        metadata={
            **{k: float(v) for k, v in result.raw_scores.items()},
            "scorer": "lub.bridge.answer_scorer",
        },
    )
    return GuardResult(
        raw=result,
        outcome=outcome,
        output=result.answer if passed else abstain_marker,
        rmf_subcategory=rmf_subcategory(decision),
    )
