# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Bridge platform entry point — dynamic agent registry + guarded routing.

This module is the *imperative* surface of the Bridge subsystem. Unlike
the constructor-bound :class:`lub.bridge.BridgePlatform` exposed from the
package ``__init__`` (which freezes its agent map at construction time),
:class:`BridgePlatform` here supports incremental agent registration so
the platform can be assembled at startup by configuration discovery (for
example, by a Bradesco deployment script that enumerates available
Azure OpenAI deployments and binds each one to a role).

The class enforces the same uncertainty-gated contract as the rest of
LUB:

1. A query is routed to the agent registered for the requested
   :class:`~lub.bridge.AgentRole` (or to the default role when none is
   given). The agent produces the customer-facing answer.
2. The agent's completion is *gated* through an
   :class:`~lub.guard.UncertaintyGuard`. The guard's policy decision
   (PASSTHROUGH / FLAG / ABSTAIN / REASK / RAISE) determines whether the
   agent's answer is released to the caller, suppressed with an abstain
   marker, or escalated to a human. **The agent's text is preserved on
   release** — the guard gates, it does not substitute.
3. When no agent is registered for the role but a
   :class:`~lub.orchestration.TieredRouter` is configured, the router
   acts as a multi-LLM failover fallback so a single misconfigured role
   does not collapse the whole platform.

Every routing decision, guard verdict, and escalation event is recorded
in :class:`~lub.bridge.BridgeResult` for downstream BCB 4893, BCBS 239,
and SR 11-7 evidence packages. When the guard's internal pipeline answer
diverges from the registered agent's answer, that divergence is also
recorded — the guard's confidence was computed against the pipeline's
own completion, so a divergence is a known uncalibrated path that the
compliance reviewer must see.

Closing the divergence calibration gap
--------------------------------------

The platform optionally accepts a
:class:`~lub.connectors.bridge.divergence_rescorer.DivergenceRescorer`.
When configured, divergent calls do not merely emit an audit event —
they are rescored against the agent's actual answer via the injected
:class:`~lub.connectors.bridge.answer_scorer.AnswerScorer`, and the
downstream policy decision is taken from the rescored verdict rather
than the pipeline-attributed one. The original guard envelope is still
recorded for replay so the BCB 4893 reviewer can confirm both the
pre- and post-rescoring decisions for each release. When no rescorer
is configured the platform falls back to the legacy "detect-only"
behaviour so deployments can adopt rescoring incrementally.

This module deliberately holds no transport state: agents are supplied
as plain callables and routers are constructed by the caller. That
keeps :class:`BridgePlatform` cheap to instantiate, safe to share across
threads (assuming the supplied collaborators are thread-safe), and easy
to unit-test with in-memory stubs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from lub.connectors.bridge import (
    AgentCallable,
    AgentResponse,
    AgentRole,
    BridgeResult,
    EscalationReason,
)
from lub.connectors.bridge import _platform_helpers as _helpers
from lub.connectors.bridge.complexity import ComplexityRouter, ComplexityScore
from lub.connectors.bridge.customer_memory import CustomerMemory
from lub.connectors.bridge.divergence_rescorer import DivergenceRescorer
from lub.connectors.bridge.memory import SemanticCache
from lub.connectors.bridge.rag import RAGPipeline, RAGResult
from lub.guard import GuardResult, UncertaintyGuard
from lub.orchestration import TieredRouter

__all__ = [
    "BridgePlatform",
    "HealthStatus",
    "PlatformHealth",
]

_LOG = structlog.get_logger("lub.bridge.platform")


# ---------------------------------------------------------------------------
# Health-check value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HealthStatus:
    """Status of a single platform collaborator (guard, router, agent).

    Attributes
    ----------
    name:
        Stable identifier used in logs (``"guard"``, ``"router"``,
        ``"agent:chatbot"``, ...).
    healthy:
        ``True`` when the collaborator is configured and responsive.
        ``False`` when the collaborator is missing or raised on probe.
    detail:
        Free-form human-readable diagnostic. Never contains PII.
    """

    name: str
    healthy: bool
    detail: str = ""


@dataclass(frozen=True)
class PlatformHealth:
    """Aggregated platform health report returned by :meth:`health_check`."""

    healthy: bool
    checks: tuple[HealthStatus, ...]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Serialize for a /healthz endpoint or compliance evidence pack."""
        return {
            "healthy": bool(self.healthy),
            "timestamp": self.timestamp.isoformat(),
            "checks": [
                {"name": c.name, "healthy": bool(c.healthy), "detail": c.detail}
                for c in self.checks
            ],
        }


# ---------------------------------------------------------------------------
# Main platform
# ---------------------------------------------------------------------------


class BridgePlatform:
    """Multi-agent platform with dynamic registration and UQ-gated routing.

    Parameters
    ----------
    guard:
        Configured :class:`~lub.guard.UncertaintyGuard` applied to every
        completion before it is returned to the caller. Sharing a single
        guard across roles keeps the calibration consistent so a
        ``chatbot`` answer and a ``call_center`` answer are scored on
        the same scale.
    router:
        Optional :class:`~lub.orchestration.TieredRouter` used as a
        cross-LLM failover path when a role has no registered agent.
        When ``None``, queries to unregistered roles escalate with
        :attr:`~lub.bridge.EscalationReason.UNKNOWN_ROLE` rather than
        falling back.
    default_role:
        Role used when :meth:`query` / :meth:`query_with_confidence`
        are called without an explicit role. Defaults to
        :attr:`~lub.bridge.AgentRole.CHATBOT`.
    divergence_rescorer:
        Optional :class:`~lub.connectors.bridge.divergence_rescorer.DivergenceRescorer`.
        When configured, divergent calls (agent answer ≠ guard
        pipeline answer) are rescored against the agent's actual
        answer so the downstream policy decision lands on a
        verdict properly attributable to the released text. The
        rescorer's audit payload is appended to the trail so
        compliance can replay both the pre- and post-rescoring
        decisions. When ``None`` (the default), divergence is only
        *detected* and logged — the legacy uncalibrated path.

    Notes
    -----
    The platform is intentionally *additive*: :meth:`register_agent`
    only appends and refuses to silently overwrite (use
    ``register_agent(..., replace=True)`` to swap). This protects against
    a misordered startup script accidentally rebinding a regulated
    role's agent.

    Gating vs substitution
    ----------------------
    When an agent is registered for a role, the guard's job is to *gate*
    the agent's answer, not replace it. The guard runs its own pipeline
    against the prompt to derive a confidence score and a policy
    decision; that decision determines release/suppression/escalation,
    but the released text is always the **agent's** answer. This matters
    when the agent has tool access, retrieval grounding, or domain
    fine-tuning that the guard's pipeline does not — substituting the
    guard's answer would silently degrade the response.

    A known limitation of this design is that the confidence score is
    technically attributed to the guard pipeline's answer, not the
    agent's. When the two diverge, an audit event
    (``query.answer_divergence``) is emitted so downstream compliance
    review can flag the call as an uncalibrated path. That gap is closed
    end-to-end when a ``divergence_rescorer`` is supplied: the rescorer
    invokes the configured
    :class:`~lub.connectors.bridge.answer_scorer.AnswerScorer` on the
    agent's text and replaces the guard verdict with one shaped
    identically to what :class:`~lub.guard.UncertaintyGuard` would have
    produced — every downstream consumer (audit trail, OTEL spans,
    AI RMF reporter, escalation classifier) keeps working without
    modification.
    """

    def __init__(
        self,
        guard: UncertaintyGuard,
        router: TieredRouter | None = None,
        default_role: AgentRole = AgentRole.CHATBOT,
        *,
        complexity: ComplexityRouter | None = None,
        cache: SemanticCache | None = None,
        customer_memory: CustomerMemory | None = None,
        rag: RAGPipeline | None = None,
        divergence_rescorer: DivergenceRescorer | None = None,
    ) -> None:
        """Construct the platform.

        The keyword-only collaborators (``complexity``, ``cache``,
        ``customer_memory``, ``rag``, ``divergence_rescorer``) are *all
        optional*. When None, the platform behaves exactly as before.
        When provided, each contributes a stage to the audit trail and
        (for ``cache``) can short-circuit the agent/router call entirely
        or (for ``divergence_rescorer``) can replace the guard verdict
        on divergent calls with one attributable to the agent's answer.
        """
        self._guard = guard
        self._router = router
        self._agents: dict[AgentRole, AgentCallable] = {}
        self._default_role = default_role
        self._complexity = complexity
        self._cache = cache
        self._customer_memory = customer_memory
        self._rag = rag
        self._divergence_rescorer = divergence_rescorer

        _LOG.info(
            "bridge.platform.initialized",
            default_role=self._default_role.value,
            router_configured=router is not None,
            complexity_configured=complexity is not None,
            cache_configured=cache is not None,
            customer_memory_configured=customer_memory is not None,
            rag_configured=rag is not None,
            divergence_rescorer_configured=divergence_rescorer is not None,
        )

    # ------------------------------------------------------------------ #
    # Inspection
    # ------------------------------------------------------------------ #

    @property
    def roles(self) -> tuple[AgentRole, ...]:
        """Roles currently registered with the platform."""
        return tuple(self._agents)

    @property
    def default_role(self) -> AgentRole:
        """Role used when no explicit role is passed to :meth:`query`."""
        return self._default_role

    @property
    def has_router(self) -> bool:
        """``True`` when a :class:`TieredRouter` failover is configured."""
        return self._router is not None

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #

    def register_agent(
        self,
        role: AgentRole,
        agent: AgentCallable,
        *,
        replace: bool = False,
    ) -> None:
        """Bind ``agent`` to ``role``.

        Parameters
        ----------
        role:
            The Bridge surface the agent serves.
        agent:
            Synchronous callable ``(prompt: str) -> str``. Wrap async
            agents at the caller side so the Bridge layer stays free of
            transport concerns.
        replace:
            When ``False`` (the default) and ``role`` is already
            registered, raises :class:`ValueError`. Set to ``True`` to
            deliberately swap an agent — useful during canary rollouts
            but logged as a warning because rebinding a regulated role
            mid-flight is a high-impact change.

        Raises
        ------
        TypeError
            If ``agent`` is not callable.
        ValueError
            If ``role`` is already registered and ``replace`` is False.
        """
        if not callable(agent):
            raise TypeError(
                f"agent for role {role.value!r} must be callable, got {type(agent).__name__}"
            )

        already = role in self._agents
        if already and not replace:
            raise ValueError(
                f"Role {role.value!r} is already registered; pass "
                f"replace=True to override deliberately."
            )

        self._agents[role] = agent
        if already:
            _LOG.warning("bridge.platform.agent_replaced", role=role.value)
        else:
            _LOG.info("bridge.platform.agent_registered", role=role.value)

    # ------------------------------------------------------------------ #
    # Query surface
    # ------------------------------------------------------------------ #

    def query(self, prompt: str, role: AgentRole | None = None) -> str:
        """Run ``prompt`` through the platform and return the final answer.

        Convenience wrapper over :meth:`query_with_confidence` for
        callers that only need the post-policy string (chatbot UI,
        IVR text-to-speech, etc.). When the underlying guard escalates,
        the returned string is the guard's abstain marker — the caller
        does not lose safety, only the structured audit trail.

        For any banking workflow that may be replayed by a regulator
        (account servicing, payment authorization, credit decisioning),
        call :meth:`query_with_confidence` instead so the
        :class:`~lub.bridge.BridgeResult` audit envelope is preserved.
        """
        return self.query_with_confidence(prompt, role).primary.answer

    def query_with_confidence(
        self,
        prompt: str,
        role: AgentRole | None = None,
        *,
        customer_id: str | None = None,
    ) -> BridgeResult:
        """Route ``prompt`` and return the full :class:`BridgeResult`.

        Routing order:

        1. ``role`` (or :attr:`default_role`) has a registered agent →
           call the agent, gate the answer with the
           :class:`~lub.guard.UncertaintyGuard`, return the result.
        2. ``role`` has no registered agent but a
           :class:`~lub.orchestration.TieredRouter` is configured →
           route through the cascade and wrap its
           :class:`~lub.orchestration.RouterResult` into a
           :class:`BridgeResult`.
        3. Otherwise → escalate with
           :attr:`~lub.bridge.EscalationReason.UNKNOWN_ROLE`.

        Agent and guard exceptions never propagate; they are recorded in
        the audit trail and surfaced as escalations so the compliance
        pipeline always observes a structured outcome.
        """
        chosen = role if role is not None else self._default_role
        audit: list[Mapping[str, Any]] = [
            {
                "event": "query.start",
                "role": chosen.value,
                "prompt_chars": len(prompt),
                "customer_id": customer_id,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        ]

        # Stage A: cache lookup (short-circuit if hit)
        if self._cache is not None:
            hit = self._cache.lookup(prompt)
            if hit is not None:
                audit.append(
                    {
                        "event": "query.cache_hit",
                        "similarity": round(hit.similarity, 3),
                        "age_seconds": round(hit.age_seconds, 1),
                        "original_intent": hit.original_intent,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )
                _LOG.info(
                    "bridge.platform.cache_hit",
                    similarity=hit.similarity,
                    age_seconds=hit.age_seconds,
                )
                return BridgeResult(
                    primary=AgentResponse(
                        role=chosen,
                        prompt=prompt,
                        answer=hit.answer,
                    ),
                    escalated=False,
                    audit_trail=tuple(audit),
                )

        # Stage B: complexity scoring (informational; tier carried in audit)
        complexity_score: ComplexityScore | None = None
        if self._complexity is not None:
            complexity_score = self._complexity.score(prompt)
            audit.append(
                {
                    "event": "query.complexity_scored",
                    "tier": complexity_score.tier.value,
                    "raw_score": complexity_score.raw_score,
                    "rationale": complexity_score.rationale,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

        # Stage C: customer memory (load persona/preferences if configured)
        if self._customer_memory is not None and customer_id:
            blocks = self._customer_memory.snapshot(customer_id)
            if blocks:
                audit.append(
                    {
                        "event": "query.customer_memory_loaded",
                        "customer_id": customer_id,
                        "block_names": list(blocks.keys()),
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )

        # Stage D: RAG retrieval (record what grounded the answer)
        rag_result: RAGResult | None = None
        if self._rag is not None:
            rag_result = self._rag.run(prompt)
            audit.append(
                {
                    "event": "query.rag_retrieved",
                    "retrieved_count": len(rag_result.retrieved),
                    "citations": list(rag_result.citations),
                    "has_grounding": rag_result.has_grounding,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

        agent = self._agents.get(chosen)
        if agent is not None:
            result = self._query_via_agent(prompt, chosen, agent, audit)
        elif self._router is not None:
            _LOG.info(
                "bridge.platform.router_fallback",
                role=chosen.value,
                reason="no_agent_registered",
            )
            audit.append(
                {
                    "event": "query.router_fallback",
                    "role": chosen.value,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            result = self._query_via_router(prompt, chosen, audit)
        else:
            _LOG.warning(
                "bridge.platform.unknown_role",
                role=chosen.value,
                known_roles=sorted(self._agents),
            )
            audit.append(
                {
                    "event": "query.unknown_role",
                    "role": chosen.value,
                    "known_roles": sorted(r.value for r in self._agents),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            result = BridgeResult(
                primary=AgentResponse(role=chosen, prompt=prompt, answer=""),
                escalated=True,
                escalation_reason=EscalationReason.UNKNOWN_ROLE,
                audit_trail=tuple(audit),
            )

        # Stage E: store successful answers in the cache for future near-matches.
        if self._cache is not None and not result.escalated and result.primary.answer:
            confidence = 0.0
            if result.primary.guard_result is not None:
                confidence = float(result.primary.guard_result.raw.confidence or 0.0)
            self._cache.store(
                prompt,
                result.primary.answer,
                intent=chosen.value,
                confidence=confidence,
            )

        return result

    # ------------------------------------------------------------------ #
    # Health check
    # ------------------------------------------------------------------ #

    def health_check(self) -> PlatformHealth:
        """Probe every collaborator and return a structured health report.

        The probe is intentionally side-effect-light: it inspects the
        configured collaborators (guard, router, agent count) but does
        not issue test prompts so health checks remain cheap to call
        from a /healthz endpoint or a Kubernetes liveness probe.
        """
        checks: list[HealthStatus] = []

        checks.append(self._probe_guard())
        checks.append(self._probe_router())
        checks.extend(self._probe_agents())

        all_healthy = all(c.healthy for c in checks)
        report = PlatformHealth(healthy=all_healthy, checks=tuple(checks))
        _LOG.info(
            "bridge.platform.health_check",
            healthy=all_healthy,
            checks=len(checks),
        )
        return report

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _query_via_agent(
        self,
        prompt: str,
        role: AgentRole,
        agent: AgentCallable,
        audit: list[Mapping[str, Any]],
    ) -> BridgeResult:
        """Execute the agent path and return a guarded :class:`BridgeResult`.

        The agent's answer is preserved end-to-end. The guard runs as a
        gate: it decides PASS/ABSTAIN/FLAG/REASK/RAISE based on its own
        pipeline's confidence, but does not substitute its pipeline's
        text for the agent's text on release. When a divergence rescorer
        is configured and the agent's answer diverges from the guard
        pipeline's answer, the guard verdict is replaced with a
        rescored verdict attributable to the agent's text before any
        downstream policy logic consumes it.
        """
        try:
            raw_answer = agent(prompt)
        except Exception as exc:  # noqa: BLE001 — surface every agent failure
            _LOG.error(
                "bridge.platform.agent_error",
                role=role.value,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            audit.append(
                {
                    "event": "query.agent_error",
                    "role": role.value,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            return BridgeResult(
                primary=AgentResponse(role=role, prompt=prompt, answer=""),
                escalated=True,
                escalation_reason=EscalationReason.AGENT_ERROR,
                audit_trail=tuple(audit),
            )

        guard_result = self._safe_guard(prompt, role, audit)

        # The guard's confidence is attributed to the guard pipeline's
        # answer, not the agent's. When they diverge, emit a structured
        # audit event so compliance can flag the call as an uncalibrated
        # path. We never block on this — divergence is informational.
        # When a divergence rescorer is configured we additionally close
        # the calibration gap end-to-end and continue with the rescored
        # verdict from this point on.
        if guard_result is not None and _helpers.answers_diverge(
            raw_answer, guard_result.raw.answer
        ):
            audit.append(
                {
                    "event": "query.answer_divergence",
                    "role": role.value,
                    "agent_answer_chars": len(raw_answer),
                    "pipeline_answer_chars": len(guard_result.raw.answer),
                    "guard_confidence": float(guard_result.raw.confidence),
                    "guard_decision": guard_result.outcome.decision.value,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            _LOG.info(
                "bridge.platform.answer_divergence",
                role=role.value,
                guard_decision=guard_result.outcome.decision.value,
                guard_confidence=f"{guard_result.raw.confidence:.4f}",
            )

            if self._divergence_rescorer is not None:
                guard_result = self._apply_divergence_rescorer(
                    prompt, raw_answer, guard_result, role, audit
                )

        final_answer = _helpers.select_answer(raw_answer, guard_result)
        response = AgentResponse(
            role=role,
            prompt=prompt,
            answer=final_answer,
            guard_result=guard_result,
        )
        escalated, reason = _helpers.classify_escalation(guard_result)
        audit.append(
            {
                "event": "query.end",
                "role": role.value,
                "escalated": escalated,
                "escalation_reason": reason.value if reason else None,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        return BridgeResult(
            primary=response,
            escalated=escalated,
            escalation_reason=reason,
            audit_trail=tuple(audit),
        )

    def _apply_divergence_rescorer(
        self,
        prompt: str,
        agent_answer: str,
        guard_result: GuardResult,
        role: AgentRole,
        audit: list[Mapping[str, Any]],
    ) -> GuardResult:
        """Run the rescorer and return the verdict that should flow downstream.

        Failures in the injected scorer are *contained*: we log the
        error, append a structured audit event marking the rescoring
        skip, and return the original ``guard_result`` so the platform
        falls back to the detect-only behaviour rather than crashing the
        query. Banking pipelines must always produce a verdict — a
        broken auxiliary signal must never turn a recoverable
        uncalibrated path into a hard failure.
        """
        rescorer = self._divergence_rescorer
        assert rescorer is not None  # noqa: S101 — guarded by caller

        try:
            outcome = rescorer.apply(prompt, agent_answer, guard_result)
        except Exception as exc:  # noqa: BLE001 — scorer is operator-supplied
            _LOG.error(
                "bridge.platform.divergence_rescorer_error",
                role=role.value,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            audit.append(
                {
                    "event": "query.divergence_rescorer_error",
                    "role": role.value,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            return guard_result

        audit.append(
            {
                "event": "query.divergence_rescored",
                "role": role.value,
                **dict(outcome.audit_payload),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if outcome.rescored and outcome.guard_result is not None:
            _LOG.info(
                "bridge.platform.divergence_rescored",
                role=role.value,
                pre_decision=guard_result.outcome.decision.value,
                post_decision=outcome.guard_result.outcome.decision.value,
                pre_confidence=f"{guard_result.raw.confidence:.4f}",
                post_confidence=f"{outcome.guard_result.raw.confidence:.4f}",
            )
            return outcome.guard_result
        return guard_result

    def _query_via_router(
        self,
        prompt: str,
        role: AgentRole,
        audit: list[Mapping[str, Any]],
    ) -> BridgeResult:
        """Execute the router fallback path and wrap the result."""
        assert self._router is not None  # noqa: S101 — guarded by caller
        try:
            routed = self._router.answer(prompt)
        except Exception as exc:  # noqa: BLE001 — failover already exhausted
            _LOG.error(
                "bridge.platform.router_error",
                role=role.value,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            audit.append(
                {
                    "event": "query.router_error",
                    "role": role.value,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            return BridgeResult(
                primary=AgentResponse(role=role, prompt=prompt, answer=""),
                escalated=True,
                escalation_reason=EscalationReason.AGENT_ERROR,
                audit_trail=tuple(audit),
            )

        guard_result = _helpers.guard_result_from_router(routed, self._guard)
        audit.append(
            {
                "event": "query.router_verdict",
                "role": role.value,
                "tier_used": routed.tier_used,
                "total_cost": float(routed.total_cost),
                "decision": guard_result.outcome.decision.value,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        response = AgentResponse(
            role=role,
            prompt=prompt,
            answer=guard_result.output,
            guard_result=guard_result,
        )
        escalated, reason = _helpers.classify_escalation(guard_result)
        audit.append(
            {
                "event": "query.end",
                "role": role.value,
                "escalated": escalated,
                "escalation_reason": reason.value if reason else None,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        return BridgeResult(
            primary=response,
            escalated=escalated,
            escalation_reason=reason,
            audit_trail=tuple(audit),
        )

    def _safe_guard(
        self,
        prompt: str,
        role: AgentRole,
        audit: list[Mapping[str, Any]],
    ) -> GuardResult | None:
        """Invoke the guard and record the verdict (or its failure)."""
        try:
            verdict = self._guard(prompt)
        except Exception as exc:  # noqa: BLE001 — guard may wrap external services
            _LOG.error(
                "bridge.platform.guard_error",
                role=role.value,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            audit.append(
                {
                    "event": "query.guard_error",
                    "role": role.value,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            return None

        audit.append(
            {
                "event": "query.guard_verdict",
                "role": role.value,
                "decision": verdict.outcome.decision.value,
                "confidence": float(verdict.raw.confidence),
                "threshold": float(verdict.outcome.threshold),
                "passed": bool(verdict.outcome.passed),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        return verdict

    # ------------------------------------------------------------------ #
    # Health probes
    # ------------------------------------------------------------------ #

    def _probe_guard(self) -> HealthStatus:
        """Check that the guard is configured with a usable threshold."""
        try:
            threshold = float(self._guard.threshold)
        except Exception as exc:  # noqa: BLE001 — probe must not raise
            return HealthStatus(
                name="guard",
                healthy=False,
                detail=f"threshold inaccessible: {type(exc).__name__}",
            )
        if not 0.0 <= threshold <= 1.0:
            return HealthStatus(
                name="guard",
                healthy=False,
                detail=f"threshold out of range: {threshold}",
            )
        return HealthStatus(
            name="guard",
            healthy=True,
            detail=f"threshold={threshold:.4f}, on_fail={self._guard.on_fail.value}",
        )

    def _probe_router(self) -> HealthStatus:
        """Check the optional router for a non-empty tier list."""
        if self._router is None:
            return HealthStatus(
                name="router",
                healthy=True,
                detail="not configured (agent-only mode)",
            )
        try:
            tier_count = len(self._router.tiers)
        except Exception as exc:  # noqa: BLE001 — probe must not raise
            return HealthStatus(
                name="router",
                healthy=False,
                detail=f"tier enumeration failed: {type(exc).__name__}",
            )
        if tier_count == 0:
            return HealthStatus(
                name="router",
                healthy=False,
                detail="router has zero tiers",
            )
        names = ",".join(t.name for t in self._router.tiers)
        return HealthStatus(
            name="router",
            healthy=True,
            detail=f"{tier_count} tier(s): {names}",
        )

    def _probe_agents(self) -> list[HealthStatus]:
        """Emit one :class:`HealthStatus` per registered agent."""
        if not self._agents:
            return [
                HealthStatus(
                    name="agents",
                    healthy=self._router is not None,
                    detail=(
                        "no agents registered; router fallback active"
                        if self._router is not None
                        else "no agents registered and no router fallback"
                    ),
                )
            ]
        return [
            HealthStatus(
                name=f"agent:{role.value}",
                healthy=callable(agent),
                detail=(
                    "callable" if callable(agent) else f"not callable ({type(agent).__name__})"
                ),
            )
            for role, agent in self._agents.items()
        ]
