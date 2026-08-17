# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""End-to-end conversation orchestrator for the Bradesco Bridge platform.

This module is the *single, channel-agnostic* entry point that ties the
four collaborators of the Bridge runtime together:

* :class:`~bridge.session.SessionManager` — durable conversation state
  (the unit of regulatory replay).
* :class:`~bridge.platform.BridgePlatform` — uncertainty-gated agent
  dispatch.
* :class:`~bridge.audit.AuditTrail` — append-only BCB 4893 / BCBS 239 /
  SR 11-7 evidence stream.
* :class:`~bridge.metrics.BridgeMetrics` — rolling counters that drive
  the 90% retention / 95% accuracy / 40% call-time-reduction headlines.

Why it exists
-------------

Until now the end-to-end flow (resolve session → append user turn →
dispatch through platform → guard → append assistant turn → write audit
entry → record metrics) only existed inside ``bridge/api/routes.py``'s
``_handle_query`` helper, tightly coupled to FastAPI request/response
models. That meant every other inbound channel — the WhatsApp Cloud
webhook in :mod:`bridge.integrations.whatsapp`, the voice transcript
adapter in :mod:`bridge.voice`, the CLI demo, and any future inbound
surface — had to reimplement the same nine-step orchestration, with the
real risk that one channel would forget to write the audit entry or
record the metric and silently break the bank's compliance posture.

:class:`ConversationOrchestrator` lifts that orchestration into a plain
Python class with a single public method::

    result = orchestrator.handle_message(
        customer_id="c123",
        channel=Channel.WHATSAPP,
        query="qual é o saldo da minha conta?",
        session_id=None,           # opens a new session
        language="pt-BR",
        intent="balance_inquiry",  # optional NLU label for metrics
    )

The returned :class:`ConversationResult` carries the post-guard answer,
guard verdict, escalation flag/reason, session id, latency, and the
audit entry id — everything an inbound channel needs to format its own
wire reply (WhatsApp text message, TTS payload, JSON body) without
touching session / audit / metrics directly.

Banking / compliance contract
-----------------------------

* **Audit-first**: when :class:`AuditTrail` write fails, the orchestrator
  raises :class:`OrchestratorAuditError` instead of silently returning
  the answer. BCB 4893 §III treats an undurable decision as a breach,
  so we prefer to abort the customer-facing reply rather than let a
  decision leave the platform without evidence. Channels that wrap the
  orchestrator are expected to surface a generic "system temporarily
  unavailable" message in this case.
* **Metrics-after**: :class:`BridgeMetrics` is updated only after the
  audit succeeds, so the headline retention / accuracy KPIs and the
  audit trail can never disagree on whether a query happened.
* **Closed sessions**: appending to a resolved or escalated session is
  treated as a client error (:class:`ConversationClosedError`) rather
  than silently opening a new conversation behind the customer's back.
* **Failure isolation**: agent exceptions, guard exceptions, and
  platform exceptions are caught inside the orchestrator, recorded as
  escalations, and surfaced as a :class:`ConversationResult` with
  ``escalated=True``. Only the audit-write failure short-circuits — it
  is the one place where silence would be a compliance issue.

The orchestrator deliberately has no transport dependencies: it is a
pure Python class. Channel adapters (FastAPI, WhatsApp, voice, CLI) wrap
it; they do not extend it.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from lub.connectors.bridge import AgentRole, BridgeResult, EscalationReason
from lub.connectors.bridge.audit import AuditDecision, AuditEntry, AuditTrail, AuditTrailError
from lub.connectors.bridge.metrics import BridgeMetrics
from lub.connectors.bridge.platform import BridgePlatform
from lub.connectors.bridge.session import (
    Channel,
    MessageRole,
    Session,
    SessionManager,
    SessionNotFoundError,
)
from lub.guard import GuardResult, PolicyDecision

__all__ = [
    "ConversationClosedError",
    "ConversationOrchestrator",
    "ConversationResult",
    "OrchestratorAuditError",
]

_LOG = structlog.get_logger("lub.bridge.orchestrator")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ConversationClosedError(RuntimeError):
    """Raised when the caller tries to append to a closed session.

    A session that has been resolved or escalated is terminal; the
    customer's next message must open a new session rather than silently
    reactivating the old one. Inbound channels translate this to a 409
    (HTTP) or to a "please start a new chat" reply (WhatsApp / voice).
    """


class OrchestratorAuditError(RuntimeError):
    """Raised when the audit-trail write fails for a real customer reply.

    BCB 4893 §III makes the durable audit record part of the decision
    itself — without it, the bank cannot demonstrate that the automated
    answer was authorised. The orchestrator therefore refuses to return
    an un-audited answer to the customer; the channel must surface a
    generic "temporarily unavailable" message and the on-call SRE must
    treat the failure as a stop-the-line incident.
    """


# ---------------------------------------------------------------------------
# Value object returned to inbound channels
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConversationResult:
    """Outcome of one end-to-end orchestrated turn.

    Frozen so a channel adapter cannot accidentally mutate a field
    between the audit write and the wire reply — the two must agree.

    Attributes
    ----------
    session_id:
        Identifier of the (existing or freshly opened) session this turn
        belongs to. The channel should round-trip this back to the
        customer so the next message continues the conversation.
    customer_id:
        Pseudonymous customer reference, identical to what the caller
        supplied (or to the synthesised ``anon-*`` id when none was
        provided).
    answer:
        Post-policy answer to return to the customer. May be the guard's
        abstain marker when the verdict suppressed the agent's raw
        completion.
    confidence:
        Guard confidence in ``[0, 1]``. Falls back to ``0.0`` when no
        guard verdict was produced (e.g. the agent raised). Distinct
        from a missing field — the metrics layer treats ``0.0`` as
        "no signal" rather than "high confidence".
    decision:
        String mirror of :class:`~lub.guard.PolicyDecision`, plus the
        platform's ``escalate`` value. Matches the audit-trail
        vocabulary so dashboards can pivot across both data sources.
    role:
        :class:`~bridge.AgentRole` that handled the dispatch.
    escalated:
        ``True`` when the guard, the agent, or the platform decided the
        turn must reach a human operator. Mirrors the session's
        terminal ``escalated`` flag after the orchestrator returns.
    escalation_reason:
        Free-form short reason string when ``escalated=True``; ``None``
        otherwise. Sourced from :class:`EscalationReason` when possible.
    latency_ms:
        End-to-end wall-clock latency of this orchestrated turn, in
        milliseconds. Captured around the platform call only — session
        I/O and audit write are excluded so the number compares to the
        SLA contract the operator agreed with the bank.
    audit_entry_id:
        Identifier of the audit row written for this turn, or ``None``
        when no audit trail was configured. Channels include this in
        their structured logs so an SRE can pivot from a complaint
        ticket to the evidence row in one step.
    metadata:
        Open-ended dict for channel-specific extras (model id, A/B
        arm, intent label). Kept off the regulatory columns so the
        audit schema stays stable.
    """

    session_id: str
    customer_id: str
    answer: str
    confidence: float
    decision: str
    role: AgentRole
    escalated: bool
    escalation_reason: str | None
    latency_ms: float
    audit_entry_id: str | None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe projection for structured logs and wire replies."""
        return {
            "session_id": self.session_id,
            "customer_id": self.customer_id,
            "answer": self.answer,
            "confidence": float(self.confidence),
            "decision": self.decision,
            "role": self.role.value,
            "escalated": bool(self.escalated),
            "escalation_reason": self.escalation_reason,
            "latency_ms": float(self.latency_ms),
            "audit_entry_id": self.audit_entry_id,
            "metadata": dict(self.metadata),
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


# Channel → default agent role mapping. The chatbot is the safe default
# for inbound text surfaces; the call-center surface is the only place
# where audio transcripts arrive, so a call-center channel routes to the
# call-center agent. Smart payments is *never* default-routed — payment
# dispatch must be triggered by an explicit intent classification so a
# casual "i'd like to pay my bill someday" never lands on the PIX/TED
# executor.
_DEFAULT_ROLE_BY_CHANNEL: dict[Channel, AgentRole] = {
    Channel.WHATSAPP: AgentRole.CHATBOT,
    Channel.MOBILE_APP: AgentRole.CHATBOT,
    Channel.WEB: AgentRole.CHATBOT,
    Channel.CALL_CENTER: AgentRole.CALL_CENTER,
}


class ConversationOrchestrator:
    """Single-method orchestrator for an end-to-end customer turn.

    Parameters
    ----------
    platform:
        Configured :class:`BridgePlatform`. The orchestrator only calls
        :meth:`BridgePlatform.query_with_confidence` so any platform
        variant exposing that method works.
    sessions:
        Configured :class:`SessionManager`. The orchestrator never
        bypasses the manager — every session write goes through
        :meth:`SessionManager.start` / :meth:`SessionManager.append` so
        the manager's lifecycle policy (TTL, idle expiry) keeps owning
        the rules.
    audit:
        Optional :class:`AuditTrail`. Strongly recommended in production
        — absence is logged at construction time and the
        ``audit_entry_id`` field of every :class:`ConversationResult`
        becomes ``None``. A misconfigured production deployment that
        omits the audit trail is itself a BCB 4893 finding.
    metrics:
        Optional :class:`BridgeMetrics`. When supplied, the orchestrator
        feeds every successful turn into the collector so the headline
        SLA dashboard reflects live traffic rather than a parallel
        counter the channel layer must remember to bump.
    model_name:
        Stable identifier of the underlying model (``"gpt-4.1-azure"``,
        ``"claude-opus-4-7"``, ``"llama-3-70b-local"``). Written verbatim
        onto every audit entry so SR 11-7 model-risk reviews can pivot
        decisions by model version without joining across log files.
    intent_classifier:
        Optional callable ``(query: str) -> str`` invoked when the
        caller does not supply an ``intent`` explicitly. Used for the
        per-intent metrics breakdown only — agent routing is decided by
        channel, not by intent, so a misclassified intent never sends a
        query to the wrong agent.

    Thread-safety
    -------------

    The orchestrator holds no mutable state of its own; it is safe to
    share across threads as long as its collaborators are. The bundled
    :class:`SessionManager`, :class:`AuditTrail`, and :class:`BridgeMetrics`
    are all thread-safe by design.
    """

    def __init__(
        self,
        *,
        platform: BridgePlatform,
        sessions: SessionManager,
        audit: AuditTrail | None = None,
        metrics: BridgeMetrics | None = None,
        model_name: str = "unknown",
        intent_classifier: Any = None,
    ) -> None:
        if platform is None:
            raise ValueError("platform is required")
        if sessions is None:
            raise ValueError("sessions is required")
        if intent_classifier is not None and not callable(intent_classifier):
            raise TypeError(
                f"intent_classifier must be callable, got {type(intent_classifier).__name__}"
            )

        self._platform = platform
        self._sessions = sessions
        self._audit = audit
        self._metrics = metrics
        self._model_name = str(model_name) if model_name else "unknown"
        self._intent_classifier = intent_classifier

        if audit is None:
            _LOG.warning(
                "bridge.orchestrator.no_audit",
                detail=(
                    "AuditTrail not supplied; BCB 4893 / SR 11-7 evidence "
                    "stream incomplete. Configure AuditTrail(path=...) before pilot."
                ),
            )
        if metrics is None:
            _LOG.info(
                "bridge.orchestrator.no_metrics",
                detail=(
                    "BridgeMetrics not supplied; rolling KPIs will rely on "
                    "SessionManager.metrics() snapshots only."
                ),
            )

        _LOG.info(
            "bridge.orchestrator.initialized",
            model_name=self._model_name,
            audit_configured=audit is not None,
            metrics_configured=metrics is not None,
            intent_classifier_configured=intent_classifier is not None,
        )

    # ------------------------------------------------------------------ #
    # Public surface
    # ------------------------------------------------------------------ #

    def handle_message(
        self,
        *,
        customer_id: str | None,
        channel: Channel,
        query: str,
        session_id: str | None = None,
        language: str = "pt-BR",
        intent: str | None = None,
        role: AgentRole | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ConversationResult:
        """Run one customer turn through the full Bridge pipeline.

        Parameters
        ----------
        customer_id:
            Pseudonymous customer reference. When ``None`` or empty, an
            ``anon-<random>`` id is synthesised so the audit row still
            has a non-empty key — required by :class:`AuditEntry`.
        channel:
            Inbound surface (WhatsApp, mobile app, web, call center).
        query:
            Customer prompt. Empty strings are accepted (some IVR voice
            transcripts come through silent); the guard will typically
            score them low and the orchestrator will escalate.
        session_id:
            Existing session to continue. When ``None`` or unknown, a
            fresh session is opened on ``channel``.
        language:
            BCP-47 language tag. Default ``pt-BR`` matches the Bradesco
            customer base; passed through to the audit ``extra`` field.
        intent:
            Optional NLU intent label. When omitted and an
            ``intent_classifier`` was supplied at construction, the
            classifier is invoked. Used only for metrics — never for
            routing.
        role:
            Override the channel's default agent role. Use sparingly —
            the channel-based default is what keeps a voice-note query
            from accidentally landing on the smart-payments executor.
        metadata:
            Open-ended per-turn metadata folded into the audit ``extra``
            and the assistant message's ``metadata``. Channels use this
            for A/B-test arms, WhatsApp message ids, etc.

        Raises
        ------
        ConversationClosedError
            The supplied ``session_id`` belongs to a session already
            terminated. Channels translate this to a 409 (HTTP) or to
            a "your previous chat is closed, starting a new one" reply.
        OrchestratorAuditError
            The audit-trail write failed. The customer-facing reply is
            *not* returned: channels must surface a generic
            "temporarily unavailable" response and trigger an alert.
        """
        started_at = time.time()
        cust = self._resolve_customer_id(customer_id)
        extra_metadata = dict(metadata or {})

        session = self._resolve_or_open_session(
            customer_id=cust,
            channel=channel,
            session_id=session_id,
        )
        self._reject_if_closed(session)

        # 1. Append the customer turn before dispatching so a crash mid-
        # request still leaves the prompt durably in the audit-friendly
        # session log.
        self._sessions.append(
            session.session_id,
            MessageRole.USER,
            query,
            metadata={
                "channel": channel.value,
                "language": language,
                **extra_metadata,
            },
        )

        chosen_role = (
            role if role is not None else _DEFAULT_ROLE_BY_CHANNEL.get(channel, AgentRole.CHATBOT)
        )

        # 2. Dispatch through the platform. All exceptions are caught
        # below so the customer never sees a 500 — they see an escalated
        # ConversationResult, the audit trail records the failure, and
        # the metrics layer sees an escalation reason.
        dispatch_started = time.time()
        try:
            result = self._platform.query_with_confidence(query, role=chosen_role)
        except Exception as exc:  # noqa: BLE001 — surface as escalation, not 500
            latency_ms = (time.time() - dispatch_started) * 1000.0
            _LOG.error(
                "bridge.orchestrator.dispatch_error",
                session_id=session.session_id,
                customer_id=cust,
                role=chosen_role.value,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return self._finalise_dispatch_failure(
                session=session,
                customer_id=cust,
                query=query,
                channel=channel,
                language=language,
                role=chosen_role,
                error=exc,
                latency_ms=latency_ms,
                started_at=started_at,
                extra=extra_metadata,
                intent=intent,
            )
        latency_ms = (time.time() - dispatch_started) * 1000.0

        confidence = _confidence_for(result)
        decision = self._audit_decision_for(result)
        escalated, escalation_reason = self._classify_escalation(result)

        # 3. Append the assistant turn, keep the guard verdict on the
        # message metadata so SessionManager.metrics() can compute the
        # 95% accuracy rate without re-reading the audit trail.
        assistant_meta: dict[str, Any] = {
            "guard_decision": decision,
            "confidence": confidence,
            "agent_role": result.primary.role.value,
            "latency_ms": latency_ms,
            **extra_metadata,
        }
        if intent is not None:
            assistant_meta["intent"] = intent
        self._sessions.append(
            session.session_id,
            MessageRole.ASSISTANT,
            result.primary.answer,
            metadata=assistant_meta,
        )

        # 4. Flip terminal session state when needed. Resolution is
        # implicit (no terminal flag set on a passthrough) so the TTL
        # sweep can later close idle but otherwise successful sessions.
        if escalated:
            self._sessions.escalate(session.session_id, reason=escalation_reason or "unknown")

        # 5. Audit write — the regulatory critical path.
        audit_entry_id = self._write_audit(
            result=result,
            customer_id=cust,
            session_id=session.session_id,
            latency_ms=latency_ms,
            channel=channel,
            language=language,
            intent=intent,
            extra=extra_metadata,
        )

        # 6. Metrics — only after the audit row is durable, so the
        # KPI dashboard cannot show traffic that has no evidence trail.
        resolved_intent = self._classify_intent(query, intent)
        self._record_metrics(
            result=result,
            latency_ms=latency_ms,
            channel=channel,
            intent=resolved_intent,
        )

        _LOG.info(
            "bridge.orchestrator.handled",
            session_id=session.session_id,
            customer_id=cust,
            role=result.primary.role.value,
            decision=decision,
            escalated=escalated,
            confidence=confidence,
            latency_ms=latency_ms,
            total_ms=(time.time() - started_at) * 1000.0,
            audit_entry_id=audit_entry_id,
        )

        return ConversationResult(
            session_id=session.session_id,
            customer_id=cust,
            answer=result.primary.answer,
            confidence=confidence,
            decision=decision,
            role=result.primary.role,
            escalated=escalated,
            escalation_reason=escalation_reason,
            latency_ms=latency_ms,
            audit_entry_id=audit_entry_id,
            metadata={
                "intent": resolved_intent,
                "language": language,
                "model_used": self._model_name,
                **extra_metadata,
            },
        )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def _resolve_customer_id(customer_id: str | None) -> str:
        """Synthesise an anonymous id when the caller did not supply one.

        :class:`AuditEntry` requires a non-empty ``customer_id``, so we
        cannot pass through ``None``. The synthesised id stays inside
        the platform — it is never sent to the customer.
        """
        if isinstance(customer_id, str) and customer_id.strip():
            return customer_id.strip()
        return f"anon-{uuid.uuid4().hex[:12]}"

    def _resolve_or_open_session(
        self,
        *,
        customer_id: str,
        channel: Channel,
        session_id: str | None,
    ) -> Session:
        """Return the named session, or open a fresh one when unknown."""
        if session_id:
            try:
                return self._sessions.get(session_id)
            except SessionNotFoundError:
                _LOG.info(
                    "bridge.orchestrator.session_not_found",
                    requested_session_id=session_id,
                    customer_id=customer_id,
                    fallback="open_new",
                )
        return self._sessions.start(customer_id=customer_id, channel=channel)

    @staticmethod
    def _reject_if_closed(session: Session) -> None:
        """Raise :class:`ConversationClosedError` for terminal sessions."""
        if session.resolved or session.escalated:
            raise ConversationClosedError(
                f"session {session.session_id!r} is closed "
                f"(resolved={session.resolved}, escalated={session.escalated})"
            )

    @staticmethod
    def _classify_escalation(
        result: BridgeResult,
    ) -> tuple[bool, str | None]:
        """Project a :class:`BridgeResult` to ``(escalated, reason_string)``."""
        if not result.escalated:
            return False, None
        reason = result.escalation_reason
        if isinstance(reason, EscalationReason):
            return True, reason.value
        return True, str(reason) if reason else "unknown"

    @staticmethod
    def _audit_decision_for(result: BridgeResult) -> str:
        """Map a :class:`BridgeResult` to the audit-trail decision label."""
        if result.escalated:
            return AuditDecision.ESCALATE
        verdict: GuardResult | None = result.primary.guard_result
        if verdict is None:
            return AuditDecision.UNKNOWN
        decision = verdict.outcome.decision
        if isinstance(decision, PolicyDecision):
            return decision.value
        if isinstance(decision, str) and decision in AuditDecision.values():
            return decision
        return AuditDecision.UNKNOWN

    def _classify_intent(self, query: str, intent: str | None) -> str | None:
        """Return the caller-supplied intent, or invoke the classifier."""
        if isinstance(intent, str) and intent.strip():
            return intent.strip()
        if self._intent_classifier is None:
            return None
        try:
            value = self._intent_classifier(query)
        except Exception as exc:  # noqa: BLE001 — never break the hot path
            _LOG.warning(
                "bridge.orchestrator.intent_classifier_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return None
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _write_audit(
        self,
        *,
        result: BridgeResult,
        customer_id: str,
        session_id: str,
        latency_ms: float,
        channel: Channel,
        language: str,
        intent: str | None,
        extra: Mapping[str, Any],
    ) -> str | None:
        """Persist the audit entry; raise :class:`OrchestratorAuditError` on failure."""
        if self._audit is None:
            return None
        try:
            entry = self._audit.log_bridge_result(
                result,
                customer_id=customer_id,
                session_id=session_id,
                model_used=self._model_name,
                latency_ms=latency_ms,
                extra={
                    "channel": channel.value,
                    "language": language,
                    "intent": intent,
                    **dict(extra),
                },
            )
        except AuditTrailError as exc:
            _LOG.error(
                "bridge.orchestrator.audit_write_failed",
                session_id=session_id,
                customer_id=customer_id,
                error=str(exc),
            )
            raise OrchestratorAuditError(
                f"audit-trail write failed for session {session_id!r}: {exc}"
            ) from exc
        return entry.entry_id

    def _record_metrics(
        self,
        *,
        result: BridgeResult,
        latency_ms: float,
        channel: Channel,
        intent: str | None,
    ) -> None:
        """Feed the metrics collector. Never raises — metrics are advisory."""
        if self._metrics is None:
            return
        try:
            self._metrics.record_query(
                result,
                latency_ms=latency_ms,
                channel=channel,
                intent=intent,
            )
        except Exception as exc:  # noqa: BLE001 — metrics must not break the hot path
            _LOG.warning(
                "bridge.orchestrator.metrics_record_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )

    def _finalise_dispatch_failure(
        self,
        *,
        session: Session,
        customer_id: str,
        query: str,
        channel: Channel,
        language: str,
        role: AgentRole,
        error: Exception,
        latency_ms: float,
        started_at: float,
        extra: Mapping[str, Any],
        intent: str | None,
    ) -> ConversationResult:
        """Record an upstream-dispatch failure and return an escalated result.

        Used when :meth:`BridgePlatform.query_with_confidence` itself
        raises before producing a :class:`BridgeResult` — the customer
        still gets a structured outcome, the session is escalated, and
        the audit trail records the dispatch failure as evidence.
        """
        escalation_reason = "dispatch_error"
        self._sessions.append(
            session.session_id,
            MessageRole.ASSISTANT,
            "",
            metadata={
                "guard_decision": AuditDecision.ESCALATE,
                "confidence": 0.0,
                "agent_role": role.value,
                "error_type": type(error).__name__,
            },
        )
        self._sessions.escalate(session.session_id, reason=escalation_reason)

        audit_entry_id: str | None = None
        if self._audit is not None:
            try:
                entry = self._audit.log_decision(
                    AuditEntry(
                        customer_id=customer_id,
                        session_id=session.session_id,
                        query=query,
                        response="",
                        confidence=None,
                        decision=AuditDecision.ESCALATE,
                        agent_used=role.value,
                        model_used=self._model_name,
                        latency_ms=latency_ms,
                        escalated=True,
                        escalation_reason=escalation_reason,
                        extra={
                            "channel": channel.value,
                            "language": language,
                            "intent": intent,
                            "error_type": type(error).__name__,
                            **dict(extra),
                        },
                    )
                )
                audit_entry_id = entry.entry_id
            except AuditTrailError as audit_exc:
                _LOG.error(
                    "bridge.orchestrator.audit_write_failed_on_dispatch_failure",
                    session_id=session.session_id,
                    error=str(audit_exc),
                )
                raise OrchestratorAuditError(
                    f"audit-trail write failed while recording dispatch error "
                    f"for session {session.session_id!r}: {audit_exc}"
                ) from audit_exc

        _LOG.warning(
            "bridge.orchestrator.dispatch_failure_finalised",
            session_id=session.session_id,
            customer_id=customer_id,
            error_type=type(error).__name__,
            latency_ms=latency_ms,
            total_ms=(time.time() - started_at) * 1000.0,
        )
        return ConversationResult(
            session_id=session.session_id,
            customer_id=customer_id,
            answer="",
            confidence=0.0,
            decision=AuditDecision.ESCALATE,
            role=role,
            escalated=True,
            escalation_reason=escalation_reason,
            latency_ms=latency_ms,
            audit_entry_id=audit_entry_id,
            metadata={
                "intent": intent,
                "language": language,
                "model_used": self._model_name,
                "error_type": type(error).__name__,
                **dict(extra),
            },
        )


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _confidence_for(result: BridgeResult) -> float:
    """Extract a clamped ``[0, 1]`` confidence from a :class:`BridgeResult`.

    Returns ``0.0`` when no guard verdict was produced (agent raised
    before the guard ran, or guard itself raised). Distinct from a
    missing field — downstream metrics treat ``0.0`` as "no signal"
    rather than "high confidence", so a single missing verdict does not
    silently inflate the 95% accuracy headline.
    """
    verdict: GuardResult | None = result.primary.guard_result
    if verdict is None:
        return 0.0
    try:
        value = float(verdict.raw.confidence)
    except (AttributeError, TypeError, ValueError):
        return 0.0
    if value != value:  # NaN guard without importing math
        return 0.0
    return max(0.0, min(1.0, value))
