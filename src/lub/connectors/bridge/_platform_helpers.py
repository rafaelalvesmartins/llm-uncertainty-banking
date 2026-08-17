# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Stateless helpers for :mod:`lub.connectors.bridge.platform`.

Extracted from ``platform.py`` to keep that module focused on the
:class:`BridgePlatform` orchestration. Each function here is pure (no
hidden state) and individually unit-testable.

Public surface
--------------
* :func:`select_answer` — picks agent vs. guard text on release.
* :func:`answers_diverge` — structural compare for audit instrumentation.
* :func:`classify_escalation` — maps a guard verdict to an escalation tuple.
* :func:`guard_result_from_router` — wraps a :class:`RouterResult` in a
  :class:`GuardResult` envelope so router-fallback queries flow through
  the same downstream consumers as agent-path queries.
"""

from __future__ import annotations

from typing import Any

from lub.connectors.bridge import EscalationReason
from lub.guard import GuardResult, PolicyDecision, UncertaintyGuard, rmf_subcategory
from lub.orchestration import RouterResult
from lub.policies import PolicyOutcome
from lub.types import UncertaintyResult

__all__ = [
    "answers_diverge",
    "classify_escalation",
    "guard_result_from_router",
    "select_answer",
]


def select_answer(
    raw_answer: str,
    verdict: GuardResult | None,
) -> str:
    """Pick the post-policy answer, preserving the agent's text.

    The guard's job is to *gate* the registered agent's answer, not
    replace it with the guard pipeline's own completion. Behaviour:

    * No verdict (guard probe failed): return the agent's answer.
      The accompanying audit event records the guard failure so the
      compliance pipeline still sees a structured outcome.
    * PASSTHROUGH, FLAG, REASK: return the agent's answer. FLAG and
      REASK are surfaced via the audit trail and escalation flag —
      the caller decides how to render the warning.
    * ABSTAIN: return ``verdict.output``, which equals the
      configured abstain marker. The agent's answer is suppressed.
    """
    if verdict is None:
        return raw_answer
    if verdict.outcome.decision is PolicyDecision.ABSTAIN:
        return verdict.output
    return raw_answer


def answers_diverge(agent_answer: str, pipeline_answer: str) -> bool:
    """Structural divergence check used for audit instrumentation only.

    The comparison is whitespace-collapsed and case-folded. It does
    not call any model and never blocks a response — it exists to
    surface a known uncalibrated path (agent ≠ guard pipeline) to
    the compliance reviewer via a structured audit event.
    """
    norm_agent = " ".join(agent_answer.split()).strip().casefold()
    norm_pipeline = " ".join(pipeline_answer.split()).strip().casefold()
    return norm_agent != norm_pipeline


def classify_escalation(
    verdict: GuardResult | None,
) -> tuple[bool, EscalationReason | None]:
    """Map a guard verdict to an escalation flag and reason."""
    if verdict is None:
        return True, EscalationReason.LOW_CONFIDENCE

    decision = verdict.outcome.decision
    if decision == PolicyDecision.PASSTHROUGH:
        return False, None
    if decision == PolicyDecision.ABSTAIN:
        return True, EscalationReason.POLICY_ABSTAIN
    if decision == PolicyDecision.FLAG:
        return True, EscalationReason.POLICY_FLAG
    # REASK and RAISE — and any future decision values — fall back to
    # the low-confidence bucket so unknown verdicts never silently
    # bypass the human-review pathway.
    return True, EscalationReason.LOW_CONFIDENCE


def guard_result_from_router(
    routed: RouterResult,
    guard: UncertaintyGuard,
) -> GuardResult:
    """Wrap a :class:`RouterResult` in a :class:`GuardResult` envelope.

    The router already enforces calibrated thresholds per tier, but
    downstream consumers (audit log, OTEL exporter, RMF reporter)
    expect a :class:`GuardResult`. We synthesize one so the rest of
    the platform handles router-fallback queries identically to
    agent-path queries.
    """
    raw: UncertaintyResult = routed.final
    passed = not raw.should_refuse
    decision = PolicyDecision.PASSTHROUGH if passed else PolicyDecision.ABSTAIN
    threshold = guard.threshold
    metadata: dict[str, Any] = {
        **dict(raw.raw_scores),
        "router_tier_used": routed.tier_used,
        "router_total_cost": float(routed.total_cost),
        "router_escalation_path": list(routed.escalation_path),
    }
    outcome = PolicyOutcome(
        decision=decision,
        confidence=float(raw.confidence),
        threshold=float(threshold),
        passed=bool(passed),
        answer=raw.answer,
        reason=(f"router tier {routed.tier_used!r} {'passed' if passed else 'abstained'}"),
        metadata=metadata,
    )
    output = raw.answer if passed else guard.abstain_marker
    return GuardResult(
        raw=raw,
        outcome=outcome,
        output=output,
        rmf_subcategory=rmf_subcategory(decision),
    )
