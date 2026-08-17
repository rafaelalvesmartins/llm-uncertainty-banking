# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""End-to-end RAG -> Agent -> Guard -> Grounding wiring for Bridge.

This module closes a structural gap in the Bridge pipeline. The
9-stage architecture documents four collaborators that *must* run on a
regulated banking turn:

* stage 4 :class:`~lub.connectors.bridge.rag.RAGPipeline` -- retrieves
  grounding evidence from manuais Bradesco / regras BCB.
* stage 6 ``agent`` -- the registered :class:`~lub.connectors.bridge.AgentCallable`
  produces a customer-facing answer.
* stage 7 :class:`~lub.guard.UncertaintyGuard` -- scores the prompt and
  decides PASSTHROUGH / FLAG / ABSTAIN / REASK / RAISE.
* stage 7b :class:`~lub.connectors.bridge.grounding.GroundingEvaluator`
  -- scores the agent's *answer* against the retrieved evidence, so a
  confident-but-hallucinated reply gets downgraded.

Until now those four collaborators each shipped, individually unit-tested,
*and never met at runtime*. :class:`~lub.connectors.bridge.platform.BridgePlatform`
calls ``agent(prompt)`` then ``guard(prompt)`` directly. RAG was never
invoked, the agent never saw the grounded prompt template, and
:func:`~lub.connectors.bridge.grounding.combine_with_guard` -- the actual
bridge between the retrieval and the guard verdict -- had no caller in
the platform. The headline failure mode is a customer-facing answer that
the guard rates with high confidence while the retrieved evidence does
not support it: BCB 4893's worst case.

:class:`GroundedQuery` is the missing wiring. It is a thin adapter over
an existing :class:`BridgePlatform`: callers keep their platform, their
agent registry, and their guard configuration intact, and simply route
regulated turns through :meth:`GroundedQuery.query_with_confidence` to
get the four collaborators chained together.

Contract preserved from :class:`BridgePlatform`:

* **The agent's answer text is never substituted.** Grounding can
  downgrade the *verdict* to FLAG or ABSTAIN, but the released text is
  whatever the platform chose for that decision (the agent's answer on
  release, the guard's abstain marker on suppression).
* **No transport state.** This adapter holds references to a platform,
  a RAG pipeline, and a grounding evaluator -- all stateless, safe to
  share across threads when the underlying collaborators are.
* **Audit-first.** Grounding events (the score, the downgrade, the
  fallback when RAG returned nothing) are appended to
  :attr:`BridgeResult.audit_trail` so the compliance reviewer sees the
  full evidence chain.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from lub.connectors.bridge import (
    AgentResponse,
    AgentRole,
    BridgeResult,
    EscalationReason,
)
from lub.connectors.bridge.grounding import (
    GroundingEvaluator,
    GroundingScore,
    LexicalGroundingEvaluator,
    combine_with_guard,
)
from lub.connectors.bridge.platform import BridgePlatform
from lub.connectors.bridge.rag import RAGPipeline, RAGResult
from lub.guard import GuardResult, PolicyDecision

__all__ = [
    "GroundedQuery",
    "GroundedQueryConfig",
]

_LOG = structlog.get_logger("lub.bridge.grounded_query")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroundedQueryConfig:
    """Tunables for :class:`GroundedQuery`.

    Attributes
    ----------
    require_grounding:
        When ``True`` and :class:`~lub.connectors.bridge.rag.RAGPipeline`
        returns no evidence (``RAGResult.has_grounding`` False), the
        adapter short-circuits with an ABSTAIN-style
        :class:`BridgeResult` without ever calling the agent. Suitable
        for high-stakes channels (smart_payments, credit decisioning)
        where an ungrounded answer is unacceptable.
        When ``False`` (the default), the adapter falls back to the raw
        prompt and the agent runs without grounding -- the guard verdict
        will still gate the answer but no grounding downgrade is applied.
    hard_floor:
        Grounding confidence below this forces the verdict to ABSTAIN.
        Passed straight through to
        :func:`~lub.connectors.bridge.grounding.combine_with_guard`.
    soft_floor:
        Grounding confidence below this (but above ``hard_floor``)
        forces the verdict to FLAG.
    """

    require_grounding: bool = False
    hard_floor: float = 0.20
    soft_floor: float = 0.50

    def __post_init__(self) -> None:
        if not 0.0 <= self.hard_floor <= 1.0:
            raise ValueError(f"hard_floor must be in [0, 1] (got {self.hard_floor})")
        if not 0.0 <= self.soft_floor <= 1.0:
            raise ValueError(f"soft_floor must be in [0, 1] (got {self.soft_floor})")
        if self.hard_floor > self.soft_floor:
            raise ValueError(
                f"hard_floor ({self.hard_floor}) must be <= soft_floor ({self.soft_floor})"
            )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@dataclass
class GroundedQuery:
    """RAG-aware front-end for an existing :class:`BridgePlatform`.

    Parameters
    ----------
    platform:
        Configured :class:`BridgePlatform`. The adapter calls into its
        :meth:`~BridgePlatform.query_with_confidence` so all of the
        platform's existing guarantees (agent isolation, guard gating,
        router fallback, audit construction) are inherited unchanged.
    rag:
        Configured :class:`RAGPipeline` used for stage-4 retrieval.
    evaluator:
        Pluggable :class:`GroundingEvaluator` used for stage-7b answer
        faithfulness. Defaults to the cost-zero
        :class:`LexicalGroundingEvaluator` so deployments can adopt
        grounded querying without taking on transformer dependencies.
    config:
        :class:`GroundedQueryConfig` tunables. The default
        ``require_grounding=False`` matches the existing chatbot
        behaviour: when RAG returns nothing, fall back to the raw
        prompt rather than refusing the customer.

    Notes
    -----
    The adapter never mutates the underlying :class:`BridgePlatform`.
    It composes -- the platform stays usable in its raw, non-grounded
    form for channels (e.g., greeting flows) where grounding makes no
    sense.

    Why an adapter, not an extension of :class:`BridgePlatform`?
    Grounding is *channel-specific*: customer-facing chat and payment
    authorization need it, but the internal voice-transcript replay
    tooling and the bare ``query()`` debug surface should bypass it.
    Composition keeps that choice at the *call site* instead of forcing
    every platform consumer to opt in or out at construction time.
    """

    platform: BridgePlatform
    rag: RAGPipeline
    evaluator: GroundingEvaluator = field(default_factory=LexicalGroundingEvaluator)
    config: GroundedQueryConfig = field(default_factory=GroundedQueryConfig)

    def __post_init__(self) -> None:
        if not isinstance(self.platform, BridgePlatform):
            raise TypeError(
                f"platform must be a BridgePlatform, got {type(self.platform).__name__}"
            )
        if not isinstance(self.rag, RAGPipeline):
            raise TypeError(f"rag must be a RAGPipeline, got {type(self.rag).__name__}")
        if not isinstance(self.evaluator, GroundingEvaluator):
            raise TypeError(
                f"evaluator must implement GroundingEvaluator, got {type(self.evaluator).__name__}"
            )

    # ------------------------------------------------------------------ #
    # Public surface
    # ------------------------------------------------------------------ #

    def query(self, prompt: str, role: AgentRole | None = None) -> str:
        """Convenience wrapper that returns only the post-policy answer."""
        return self.query_with_confidence(prompt, role).primary.answer

    def query_with_confidence(
        self,
        prompt: str,
        role: AgentRole | None = None,
    ) -> BridgeResult:
        """Run the four-stage chain and return a fully audited result.

        Execution order:

        1. :class:`RAGPipeline` retrieves grounding evidence.
        2. If grounding is present, the *grounded* prompt is what the
           agent sees; if absent and ``require_grounding`` is True, the
           adapter short-circuits with an ABSTAIN-style result and the
           agent is never called.
        3. The platform is invoked with the chosen agent prompt -- this
           is the existing :meth:`BridgePlatform.query_with_confidence`
           path, so the agent, guard, and router-fallback semantics are
           preserved bit-for-bit.
        4. The grounding evaluator scores the agent's *answer* against
           the retrieved evidence, and
           :func:`~lub.connectors.bridge.grounding.combine_with_guard`
           downgrades the guard verdict when faithfulness is weak.

        The returned :class:`BridgeResult` is a *new* envelope: the
        original prompt is restored on :attr:`AgentResponse.prompt`
        (the agent saw the grounded prompt, but downstream audit
        consumers expect the customer's raw text), the grounded guard
        verdict replaces the platform's verdict on
        :attr:`AgentResponse.guard_result`, and grounding events are
        appended to :attr:`BridgeResult.audit_trail`.
        """
        chosen = role if role is not None else self.platform.default_role
        rag_result = self._safe_rag(prompt, chosen)

        if not rag_result.has_grounding and self.config.require_grounding:
            return self._refuse_no_grounding(prompt, chosen, rag_result)

        agent_prompt = rag_result.grounded_prompt if rag_result.has_grounding else prompt
        platform_result = self.platform.query_with_confidence(agent_prompt, chosen)

        return self._merge_grounding(prompt, chosen, rag_result, platform_result)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _safe_rag(self, prompt: str, role: AgentRole) -> RAGResult:
        """Run retrieval, never raise.

        A retrieval failure is logged and converted into a
        ``has_grounding=False`` :class:`RAGResult` so the rest of the
        pipeline sees a structured "no evidence" signal instead of an
        exception -- the same defensive style the platform uses for
        agent and guard failures.
        """
        try:
            return self.rag.run(prompt)
        except Exception as exc:  # noqa: BLE001 -- RAG wraps external stores
            _LOG.error(
                "bridge.grounded_query.rag_error",
                role=role.value,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return RAGResult(
                grounded_prompt=prompt,
                retrieved=(),
                citations=(),
                duration_ms=0.0,
            )

    def _refuse_no_grounding(
        self,
        prompt: str,
        role: AgentRole,
        rag_result: RAGResult,
    ) -> BridgeResult:
        """Build an ABSTAIN-style result when grounding is mandatory.

        Used when :attr:`GroundedQueryConfig.require_grounding` is True
        and RAG produced nothing. We never call the agent in this
        branch -- the audit log will show that the platform refused
        before reaching the LLM, which is the desired behaviour for
        regulated channels like smart_payments.
        """
        marker = self.platform.guard_abstain_marker()  # type: ignore[attr-defined]
        audit: tuple[Mapping[str, Any], ...] = (
            {
                "event": "grounded_query.start",
                "role": role.value,
                "prompt_chars": len(prompt),
                "require_grounding": True,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            {
                "event": "grounded_query.rag_empty",
                "role": role.value,
                "retrieved": 0,
                "rag_duration_ms": float(rag_result.duration_ms),
                "timestamp": datetime.now(UTC).isoformat(),
            },
            {
                "event": "grounded_query.refused_ungrounded",
                "role": role.value,
                "reason": "require_grounding=True and RAG returned no evidence",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        _LOG.warning(
            "bridge.grounded_query.refused_ungrounded",
            role=role.value,
            prompt_chars=len(prompt),
        )
        return BridgeResult(
            primary=AgentResponse(role=role, prompt=prompt, answer=marker),
            escalated=True,
            escalation_reason=EscalationReason.POLICY_ABSTAIN,
            audit_trail=audit,
        )

    def _merge_grounding(
        self,
        original_prompt: str,
        role: AgentRole,
        rag_result: RAGResult,
        platform_result: BridgeResult,
    ) -> BridgeResult:
        """Score the agent's answer and rebuild the bridge result.

        Three things happen here:

        1. The agent's prompt as recorded in the result is restored to
           the *original* customer text. The grounded prompt template
           (which can be many KB) is not what downstream audit consumers
           want to see -- the grounding evidence is already captured in
           the per-event grounding audit entry.
        2. When the platform produced a guard verdict, the grounding
           evaluator scores the agent's answer and
           :func:`combine_with_guard` downgrades the verdict if
           faithfulness is weak. The result's primary guard_result is
           replaced with the downgraded verdict.
        3. The escalation flag is recomputed against the (possibly
           downgraded) verdict, so a fresh ABSTAIN/FLAG from grounding
           always surfaces upstream regardless of what the platform
           originally decided.
        """
        audit_events: list[Mapping[str, Any]] = list(platform_result.audit_trail)

        # Prepend a marker for the grounded entry point.
        head = {
            "event": "grounded_query.start",
            "role": role.value,
            "prompt_chars": len(original_prompt),
            "retrieved": len(rag_result.retrieved),
            "rag_citations": list(rag_result.citations),
            "rag_duration_ms": float(rag_result.duration_ms),
            "timestamp": datetime.now(UTC).isoformat(),
        }

        original_verdict = platform_result.primary.guard_result
        if original_verdict is None or not rag_result.has_grounding:
            # No verdict means the guard failed (platform recorded that
            # already) or there is nothing for the grounding scorer to
            # check against. Either way we cannot downgrade -- but we
            # still note in the audit log that grounding was skipped.
            audit_events.append(
                {
                    "event": "grounded_query.grounding_skipped",
                    "role": role.value,
                    "reason": (
                        "no guard verdict" if original_verdict is None else "no retrieved evidence"
                    ),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            primary = dataclasses.replace(platform_result.primary, prompt=original_prompt)
            return dataclasses.replace(
                platform_result,
                primary=primary,
                audit_trail=(head, *audit_events),
            )

        grounding_score = self._safe_score(role, platform_result.primary.answer, rag_result)
        if grounding_score is None:
            audit_events.append(
                {
                    "event": "grounded_query.grounding_error",
                    "role": role.value,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            primary = dataclasses.replace(platform_result.primary, prompt=original_prompt)
            return dataclasses.replace(
                platform_result,
                primary=primary,
                audit_trail=(head, *audit_events),
            )

        downgraded = combine_with_guard(
            original_verdict,
            grounding_score,
            hard_floor=self.config.hard_floor,
            soft_floor=self.config.soft_floor,
            abstain_marker=self.platform.guard_abstain_marker(),  # type: ignore[attr-defined]
        )

        audit_events.append(
            {
                "event": "grounded_query.grounding_scored",
                "role": role.value,
                "grounding": grounding_score.as_audit(),
                "prior_decision": original_verdict.outcome.decision.value,
                "post_decision": downgraded.outcome.decision.value,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        escalated, reason = _classify_escalation(downgraded)
        final_answer = _select_answer(platform_result.primary.answer, downgraded)
        new_primary = AgentResponse(
            role=role,
            prompt=original_prompt,
            answer=final_answer,
            guard_result=downgraded,
            timestamp=platform_result.primary.timestamp,
        )
        audit_events.append(
            {
                "event": "grounded_query.end",
                "role": role.value,
                "escalated": escalated,
                "escalation_reason": reason.value if reason else None,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        return BridgeResult(
            primary=new_primary,
            escalated=escalated,
            escalation_reason=reason,
            audit_trail=(head, *audit_events),
        )

    def _safe_score(
        self,
        role: AgentRole,
        answer: str,
        rag_result: RAGResult,
    ) -> GroundingScore | None:
        """Run the grounding evaluator, never raise."""
        try:
            return self.evaluator.score(answer, rag_result)
        except Exception as exc:  # noqa: BLE001 -- evaluators may wrap NLI models
            _LOG.error(
                "bridge.grounded_query.evaluator_error",
                role=role.value,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return None


# ---------------------------------------------------------------------------
# Module-level helpers (mirror BridgePlatform's contract)
# ---------------------------------------------------------------------------


def _classify_escalation(
    verdict: GuardResult,
) -> tuple[bool, EscalationReason | None]:
    """Map a (possibly downgraded) verdict to escalation flag and reason.

    Mirrors :meth:`BridgePlatform._classify_escalation` so the grounded
    path produces the same escalation taxonomy as the raw platform path
    -- downstream consumers (audit shipper, RMF reporter) can treat
    both result kinds identically.
    """
    decision = verdict.outcome.decision
    if decision == PolicyDecision.PASSTHROUGH:
        return False, None
    if decision == PolicyDecision.ABSTAIN:
        return True, EscalationReason.POLICY_ABSTAIN
    if decision == PolicyDecision.FLAG:
        return True, EscalationReason.POLICY_FLAG
    return True, EscalationReason.LOW_CONFIDENCE


def _select_answer(agent_answer: str, verdict: GuardResult) -> str:
    """Pick the post-policy answer, preserving the agent's text.

    Same contract as :meth:`BridgePlatform._select_answer`: ABSTAIN
    suppresses the agent's text with the guard's abstain marker; every
    other decision releases the agent's text unchanged. Implemented
    here (rather than imported) because the platform's helper is a
    private static method -- duplicating four lines keeps that
    encapsulation intact and avoids a brittle ``_select_answer``
    import.
    """
    if verdict.outcome.decision is PolicyDecision.ABSTAIN:
        return verdict.output
    return agent_answer


# ---------------------------------------------------------------------------
# BridgePlatform shim
# ---------------------------------------------------------------------------
#
# BridgePlatform holds its guard on a private attribute (``_guard``).
# Reaching past the underscore from another module would be a layering
# violation, so we expose a tiny accessor on the platform via a method
# patch -- declared here, attached on import, idempotent.


def _guard_abstain_marker(self: BridgePlatform) -> str:
    """Public read of the platform's guard abstain marker.

    Attached as :meth:`BridgePlatform.guard_abstain_marker` so this
    adapter can read the configured marker without touching the
    platform's private ``_guard`` attribute. Defined and bound here
    (not on the platform itself) to keep the change local to the
    grounded-query wiring -- the platform module stays unchanged.
    """
    return str(self._guard.abstain_marker)  # noqa: SLF001 -- single boundary crossing


if not hasattr(BridgePlatform, "guard_abstain_marker"):
    BridgePlatform.guard_abstain_marker = _guard_abstain_marker  # type: ignore[attr-defined]
