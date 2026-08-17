# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Wire :mod:`answer_scorer` into the Bridge pipeline at the divergence site.

:mod:`lub.connectors.bridge.platform` already detects when the agent's
answer diverges from the guard pipeline's answer and emits a
``query.answer_divergence`` audit event — but it does nothing about it.
The guard's verdict is still consumed downstream even though its
confidence was attributed to the *guard pipeline's* text, not the
agent's. That is the gap :mod:`answer_scorer` was built to close;
this module is the adapter that puts the rescorer on the pipeline.

The contract is intentionally narrow so it composes with the existing
flow rather than replacing it:

* :class:`DivergenceRescorer` accepts a Protocol-typed
  :class:`~lub.connectors.bridge.answer_scorer.AnswerScorer` and an
  optional threshold override. Default behaviour is to inherit the
  upstream guard's threshold, so the rescored decision lands on the
  same policy boundary the operator already chose.
* :meth:`DivergenceRescorer.apply` is a no-op (returns the guard
  result unchanged, marked ``rescored=False``) when the answers do
  not diverge. This makes the rescorer cheap to enable platform-wide
  — only divergent calls pay the scoring cost.
* When divergent, it calls the scorer on ``(prompt, agent_answer)``
  and returns a fresh :class:`~lub.guard.GuardResult` produced by
  :func:`~lub.connectors.bridge.answer_scorer.gate_answer_score`. The
  envelope is shaped identically to what
  :class:`~lub.guard.UncertaintyGuard` would have emitted, so every
  downstream consumer — audit trail, OTEL spans, AI RMF reporter,
  escalation classifier — keeps working without modification.

The module returns a :class:`RescoringOutcome` rather than just a
``GuardResult`` so the caller can record an audit event that names
both pre- and post-rescoring decisions. That structured trail is what
the BCB 4893 reviewer needs to verify the calibration gap was
actually closed for a given release, not just instrumented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from lub.connectors.bridge._platform_helpers import answers_diverge
from lub.connectors.bridge.answer_scorer import AnswerScorer, gate_answer_score
from lub.guard import GuardResult

__all__ = [
    "DEFAULT_RESCORED_ABSTAIN_MARKER",
    "DivergenceRescorer",
    "RescoringOutcome",
    "rescore_on_divergence",
]

_LOG = structlog.get_logger("lub.bridge.divergence_rescorer")

DEFAULT_RESCORED_ABSTAIN_MARKER = "[ABSTAIN: answer-attributed confidence below threshold]"


@dataclass(frozen=True)
class RescoringOutcome:
    """Result of running the divergence rescorer over one query.

    Attributes
    ----------
    guard_result:
        The :class:`~lub.guard.GuardResult` to feed downstream. Equals
        the input guard result when no rescoring happened; equals a
        freshly minted envelope (attributable to the agent's text)
        when rescoring fired.
    rescored:
        ``True`` if the scorer was invoked and the returned
        ``guard_result`` is the post-hoc verdict. ``False`` if the
        input was returned unchanged (no divergence, or no upstream
        guard result to compare against).
    audit_payload:
        Structured fields ready to merge into the Bridge audit
        trail. Caller stamps ``event``, ``role``, and ``timestamp``
        — the rescorer stays agnostic of those so it composes with
        whatever orchestration shape the platform evolves toward.
        Always present, even when ``rescored=False``, so the
        compliance reviewer sees that the rescorer was consulted.
    """

    guard_result: GuardResult | None
    rescored: bool
    audit_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DivergenceRescorer:
    """Apply a post-hoc :class:`AnswerScorer` only when the agent diverges.

    Parameters
    ----------
    scorer:
        The injected :class:`AnswerScorer`. The factory choice
        (lexical self-consistency vs. p_true vs. composite) is the
        operator's call — this adapter is content-agnostic.
    threshold_override:
        Optional explicit threshold in ``[0, 1]``. When ``None`` (the
        default) the upstream guard's threshold is reused so the
        rescored decision lands on the same policy boundary the
        operator already chose. Set this only when you need an
        intentionally different bar for rescored paths (e.g., a more
        conservative gate for known-divergent flows).
    abstain_marker:
        String returned in ``GuardResult.output`` when the rescored
        verdict abstains. Defaults to a marker distinct from the
        upstream guard's so an audit reader can tell which gate fired.

    Raises
    ------
    ValueError
        If ``threshold_override`` is set but outside ``[0, 1]``.
    """

    scorer: AnswerScorer
    threshold_override: float | None = None
    abstain_marker: str = DEFAULT_RESCORED_ABSTAIN_MARKER

    def __post_init__(self) -> None:
        if self.threshold_override is not None and not (0.0 <= self.threshold_override <= 1.0):
            raise ValueError(f"threshold_override must be in [0, 1], got {self.threshold_override}")

    def apply(
        self,
        prompt: str,
        agent_answer: str,
        guard_result: GuardResult | None,
    ) -> RescoringOutcome:
        """Return a :class:`RescoringOutcome` attributable to ``agent_answer``.

        Behaviour matrix:

        * ``guard_result is None`` — the upstream guard probe failed.
          Return ``rescored=False`` and a payload marking the skip.
          The platform already records the guard failure separately;
          this module declines to fabricate a verdict from a single
          unverified signal.
        * Answers do not diverge — the guard's confidence already
          applies to the agent's text (up to the structural
          comparison in :func:`answers_diverge`). Return the input
          unchanged with ``rescored=False`` and a payload recording
          the cheap short-circuit.
        * Answers diverge — call ``scorer.score(prompt, agent_answer)``,
          wrap via :func:`gate_answer_score` at the resolved
          threshold, and return ``rescored=True`` with a payload
          carrying both pre- and post-rescoring decisions so
          compliance can confirm the gap was closed.
        """
        if guard_result is None:
            return RescoringOutcome(
                guard_result=None,
                rescored=False,
                audit_payload={
                    "rescored": False,
                    "skip_reason": "no_guard_result",
                },
            )

        pipeline_answer = guard_result.raw.answer
        if not answers_diverge(agent_answer, pipeline_answer):
            return RescoringOutcome(
                guard_result=guard_result,
                rescored=False,
                audit_payload={
                    "rescored": False,
                    "skip_reason": "answers_aligned",
                    "pipeline_confidence": float(guard_result.raw.confidence),
                    "pipeline_decision": guard_result.outcome.decision.value,
                },
            )

        threshold = (
            self.threshold_override
            if self.threshold_override is not None
            else float(guard_result.outcome.threshold)
        )
        score = self.scorer.score(prompt, agent_answer)
        rescored_guard = gate_answer_score(
            score,
            threshold=threshold,
            abstain_marker=self.abstain_marker,
        )

        _LOG.info(
            "bridge.divergence_rescorer.rescored",
            pipeline_decision=guard_result.outcome.decision.value,
            pipeline_confidence=f"{guard_result.raw.confidence:.4f}",
            rescored_decision=rescored_guard.outcome.decision.value,
            rescored_confidence=f"{score.confidence:.4f}",
            threshold=f"{threshold:.4f}",
        )

        return RescoringOutcome(
            guard_result=rescored_guard,
            rescored=True,
            audit_payload={
                "rescored": True,
                "scorer": "lub.bridge.answer_scorer",
                "threshold": float(threshold),
                "agent_confidence": float(score.confidence),
                "agent_decision": rescored_guard.outcome.decision.value,
                "pipeline_confidence": float(guard_result.raw.confidence),
                "pipeline_decision": guard_result.outcome.decision.value,
                "agent_should_refuse": bool(score.should_refuse),
            },
        )


def rescore_on_divergence(
    prompt: str,
    agent_answer: str,
    guard_result: GuardResult | None,
    scorer: AnswerScorer,
    *,
    threshold_override: float | None = None,
    abstain_marker: str = DEFAULT_RESCORED_ABSTAIN_MARKER,
) -> RescoringOutcome:
    """One-call convenience wrapper around :class:`DivergenceRescorer`.

    Intended for inline use at the platform divergence site so the
    wire-up is a single import plus a single call — no extra state
    threaded through :class:`~lub.connectors.bridge.platform.BridgePlatform`.
    For repeated use with a stable scorer (the common case once a
    deployment picks its rescoring strategy), construct a
    :class:`DivergenceRescorer` once and call :meth:`apply` directly
    to avoid rebuilding the dataclass per query.
    """
    return DivergenceRescorer(
        scorer=scorer,
        threshold_override=threshold_override,
        abstain_marker=abstain_marker,
    ).apply(prompt, agent_answer, guard_result)
