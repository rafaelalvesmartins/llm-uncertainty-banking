# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Bridge platform — multi-agent orchestrator for banking AI.

Coordinates the three flagship Bradesco Bridge surfaces — *chatbot*,
*call center*, and *smart payments* — behind a single uncertainty-gated
entry point. Every agent invocation is wrapped in an
:class:`~lub.guard.UncertaintyGuard` so that low-confidence completions
are surfaced (FLAG), suppressed (ABSTAIN), or escalated to a human
operator rather than returned blindly to a customer.

Reference metrics from the Bradesco production deployment (used here
only as documentation, never as hard-coded thresholds):

* **83%** end-to-end resolution rate
* **89%** customer retention without escalation
* **8×** operator productivity gain

Regulatory surface
------------------

Bridge sits in the path of regulated banking workflows, so this module
enforces an *audit trail by construction*: every routing decision, guard
verdict, and escalation event is recorded in :class:`BridgeResult` and
can be replayed for BCB 4893, BCBS 239, and SR 11-7 evidence packages.

This module deliberately keeps no network dependencies of its own — it
is a coordinator that wires user-supplied agent callables to an
:class:`~lub.guard.UncertaintyGuard`, leaving HTTP/SDK concerns to the
caller (typically a :mod:`lub.wrappers` backend).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

from lub.guard import GuardResult, PolicyDecision, UncertaintyGuard

__all__ = [
    "AgentRole",
    "AgentResponse",
    "BridgePlatform",
    "BridgeResult",
    "EscalationReason",
]

log = structlog.get_logger(__name__)


class AgentRole(StrEnum):
    """Roles served by the Bridge platform.

    Mirrors the three Bradesco Bridge surfaces. New roles must be added
    here so the routing table stays exhaustive — :class:`BridgePlatform`
    refuses to dispatch to a role that is not registered.
    """

    CHATBOT = "chatbot"
    CALL_CENTER = "call_center"
    SMART_PAYMENTS = "smart_payments"


class EscalationReason(StrEnum):
    """Why a Bridge call was escalated out of the automated path."""

    LOW_CONFIDENCE = "low_confidence"
    POLICY_ABSTAIN = "policy_abstain"
    POLICY_FLAG = "policy_flag"
    AGENT_ERROR = "agent_error"
    UNKNOWN_ROLE = "unknown_role"


AgentCallable = Callable[[str], str]
"""Signature of an agent: take a prompt, return a raw completion.

Agents are deliberately synchronous and stringly-typed to keep the
Bridge layer free of transport concerns. Wrap async or structured
agents at the caller side.
"""


@dataclass(frozen=True)
class AgentResponse:
    """Single agent's reply, with the guard verdict that gated it."""

    role: AgentRole
    prompt: str
    answer: str
    guard_result: GuardResult | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class BridgeResult:
    """Aggregated outcome of a Bridge dispatch.

    Holds the primary agent response plus any escalation metadata. The
    ``audit_trail`` is an append-only list of structured events ready to
    be shipped to a SIEM or compliance lake — never mutate it after the
    result is returned.
    """

    primary: AgentResponse
    escalated: bool = False
    escalation_reason: EscalationReason | None = None
    audit_trail: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)


class BridgePlatform:
    """Multi-agent orchestrator with uncertainty guardrails.

    Parameters
    ----------
    guard:
        Configured :class:`~lub.guard.UncertaintyGuard` used to score
        every agent reply. Sharing one guard across roles keeps the
        confidence calibration consistent platform-wide.
    agents:
        Mapping from :class:`AgentRole` to a synchronous callable that
        produces a raw completion for a prompt. Roles missing from the
        mapping cannot be dispatched to.
    default_role:
        Role used when :meth:`dispatch` is called without an explicit
        role. Defaults to :attr:`AgentRole.CHATBOT` because the chatbot
        surface handles the majority of Bradesco Bridge traffic.

    Notes
    -----
    The platform is intentionally stateless beyond its construction
    parameters; per-request state lives in :class:`BridgeResult`. This
    makes :class:`BridgePlatform` safe to share across threads as long
    as the supplied ``guard`` and agent callables are themselves
    thread-safe.
    """

    def __init__(
        self,
        guard: UncertaintyGuard,
        agents: Mapping[AgentRole, AgentCallable],
        default_role: AgentRole = AgentRole.CHATBOT,
    ) -> None:
        if not agents:
            raise ValueError("BridgePlatform requires at least one registered agent")
        if default_role not in agents:
            raise ValueError(
                f"default_role {default_role!r} is not in registered agents {sorted(agents)!r}"
            )

        self._guard = guard
        self._agents: dict[AgentRole, AgentCallable] = dict(agents)
        self._default_role = default_role

        log.info(
            "bridge.platform.initialized",
            roles=sorted(self._agents),
            default_role=self._default_role.value,
        )

    @property
    def roles(self) -> tuple[AgentRole, ...]:
        """Roles currently registered with the platform."""
        return tuple(self._agents)

    @property
    def default_role(self) -> AgentRole:
        """Role used when :meth:`dispatch` is called without an explicit role."""
        return self._default_role

    def dispatch(
        self,
        prompt: str,
        role: AgentRole | None = None,
    ) -> BridgeResult:
        """Route ``prompt`` to the agent for ``role`` and gate the reply.

        Returns a :class:`BridgeResult` whose ``escalated`` flag is set
        when the underlying guard policy did anything other than
        :attr:`~lub.guard.PolicyDecision.PASSTHROUGH`, or when the agent
        itself raised. Never raises for an unknown role — instead emits
        an escalation result so the caller's compliance pipeline always
        sees a record.
        """
        chosen = role if role is not None else self._default_role
        audit: list[Mapping[str, Any]] = []

        audit.append(
            {
                "event": "dispatch.start",
                "role": chosen.value,
                "prompt_chars": len(prompt),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        agent = self._agents.get(chosen)
        if agent is None:
            log.warning(
                "bridge.dispatch.unknown_role",
                role=chosen.value,
                known_roles=sorted(self._agents),
            )
            audit.append(
                {
                    "event": "dispatch.unknown_role",
                    "role": chosen.value,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            return BridgeResult(
                primary=AgentResponse(
                    role=chosen,
                    prompt=prompt,
                    answer="",
                ),
                escalated=True,
                escalation_reason=EscalationReason.UNKNOWN_ROLE,
                audit_trail=tuple(audit),
            )

        try:
            raw_answer = agent(prompt)
        except Exception as exc:  # noqa: BLE001 — surface every agent failure as escalation
            log.error(
                "bridge.dispatch.agent_error",
                role=chosen.value,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            audit.append(
                {
                    "event": "dispatch.agent_error",
                    "role": chosen.value,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            return BridgeResult(
                primary=AgentResponse(
                    role=chosen,
                    prompt=prompt,
                    answer="",
                ),
                escalated=True,
                escalation_reason=EscalationReason.AGENT_ERROR,
                audit_trail=tuple(audit),
            )

        guard_result = self._run_guard(prompt, audit, role=chosen)

        final_answer = guard_result.output if guard_result is not None else raw_answer

        response = AgentResponse(
            role=chosen,
            prompt=prompt,
            answer=final_answer,
            guard_result=guard_result,
        )

        escalated, reason = self._classify_escalation(guard_result)
        audit.append(
            {
                "event": "dispatch.end",
                "role": chosen.value,
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

    def _run_guard(
        self,
        prompt: str,
        audit: list[Mapping[str, Any]],
        *,
        role: AgentRole,
    ) -> GuardResult | None:
        """Invoke the uncertainty guard and append an audit event.

        Guard failures are logged but never propagated — a missing guard
        verdict is itself recorded so reviewers can spot it during
        compliance review.
        """
        try:
            verdict = self._guard(prompt)
        except Exception as exc:  # noqa: BLE001 — guards may wrap external services
            log.error(
                "bridge.dispatch.guard_error",
                role=role.value,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            audit.append(
                {
                    "event": "dispatch.guard_error",
                    "role": role.value,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            return None

        audit.append(
            {
                "event": "dispatch.guard_verdict",
                "role": role.value,
                "decision": _decision_value(verdict),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        return verdict

    @staticmethod
    def _classify_escalation(
        verdict: GuardResult | None,
    ) -> tuple[bool, EscalationReason | None]:
        """Map a :class:`GuardResult` to an escalation flag and reason."""
        if verdict is None:
            return True, EscalationReason.LOW_CONFIDENCE

        decision = _extract_decision(verdict)
        if decision is None or decision == PolicyDecision.PASSTHROUGH:
            return False, None
        if decision == PolicyDecision.ABSTAIN:
            return True, EscalationReason.POLICY_ABSTAIN
        if decision == PolicyDecision.FLAG:
            return True, EscalationReason.POLICY_FLAG
        # RAISE and any future decision values default to low-confidence
        # escalation so an unknown verdict never silently passes through.
        return True, EscalationReason.LOW_CONFIDENCE


def _extract_decision(verdict: GuardResult) -> PolicyDecision | None:
    """Pull the :class:`PolicyDecision` out of a guard result, if present.

    Current :class:`GuardResult` exposes the decision via
    ``outcome.decision``; older duck-typed shapes used ``policy_outcome``
    or a top-level ``decision`` attribute. This helper accepts all three
    so the legacy dispatch path stays compatible with mocks while
    correctly reading real :class:`GuardResult` instances.
    """
    outcome = getattr(verdict, "outcome", None) or getattr(verdict, "policy_outcome", None)
    if outcome is None:
        return getattr(verdict, "decision", None)
    return getattr(outcome, "decision", None)


def _decision_value(verdict: GuardResult | None) -> str | None:
    """Serialize a guard verdict's decision for audit logs."""
    if verdict is None:
        return None
    decision = _extract_decision(verdict)
    return decision.value if decision is not None else None
