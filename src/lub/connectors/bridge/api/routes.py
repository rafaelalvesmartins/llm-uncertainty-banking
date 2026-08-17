# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""FastAPI route definitions for the Bridge platform.

This module is the public REST surface for the Bradesco Bridge — the
endpoint a WhatsApp webhook handler, mobile-app gateway, web chat
widget, or call-center desktop hits when a customer asks the bank
something. It exposes:

* ``POST /query`` — the single end-to-end customer entry point. Persists
  the conversation in a :class:`~lub.bridge.session.SessionManager`,
  dispatches through a :class:`~lub.bridge.platform.BridgePlatform` so
  every reply is gated by the :class:`~lub.guard.UncertaintyGuard`, and
  appends an :class:`~lub.bridge.audit.AuditEntry` to the BCB 4893
  trail.
* ``GET /metrics`` — derived from :meth:`SessionManager.metrics` so the
  90% retention / 95% accuracy headlines come from real conversation
  state, not a counter incremented at the edge.
* ``GET /health`` — runs :meth:`BridgePlatform.health_check` so a
  Kubernetes liveness probe sees actual collaborator state.
* ``GET /compliance`` — surfaces audit-trail coverage as the primary
  BCB 4893 / BCBS 239 / SR 11-7 evidence signal.
* ``GET /agents`` and ``POST /agents/register`` — read/write the
  platform's registered roles.

Wiring contract
---------------

:func:`create_app` is a dependency-injected factory. Pass in the
collaborators the deployment script constructed at startup::

    from lub.connectors.bridge.api.routes import create_app
    from lub.connectors.bridge.audit import AuditTrail
    from lub.connectors.bridge.platform import BridgePlatform
    from lub.connectors.bridge.session import InMemorySessionStore, SessionManager
    from lub.guard import UncertaintyGuard

    platform = BridgePlatform(guard=UncertaintyGuard(...))
    platform.register_agent(AgentRole.CHATBOT, my_chatbot_callable)
    sessions = SessionManager(InMemorySessionStore())
    audit = AuditTrail("/var/log/bridge/audit.jsonl")

    app = create_app(platform=platform, sessions=sessions, audit=audit)

When ``platform`` is ``None`` the factory still returns a usable app
that responds to ``/health`` and ``/metrics`` with zero-state stubs.
That mode is kept only for local smoke-testing — a production
deployment that omits the platform is itself a compliance breach (no
audit trail, no guard) and is logged loudly at startup.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from fastapi import HTTPException

from lub.connectors.bridge import AgentRole, BridgeResult, EscalationReason
from lub.connectors.bridge.api.models import (
    AgentInfo,
    AgentRegisterRequest,
    ComplianceResponse,
    Decision,
    HealthResponse,
    MetricsResponse,
    QueryRequest,
    QueryResponse,
)
from lub.connectors.bridge.audit import AuditDecision, AuditEntry, AuditTrail
from lub.connectors.bridge.platform import BridgePlatform
from lub.connectors.bridge.session import (
    Channel as SessionChannel,
)
from lub.connectors.bridge.session import (
    MessageRole,
    SessionManager,
    SessionNotFoundError,
)
from lub.guard import GuardResult, PolicyDecision

__all__ = ["create_app"]

_LOG = structlog.get_logger("lub.api")


# ---------------------------------------------------------------------------
# Channel / role / decision mapping
# ---------------------------------------------------------------------------

# Channel values from `lub.api.models.Channel` -> `lub.bridge.session.Channel`.
# The two enums disagree on one value (`app` vs `mobile_app`) for historical
# reasons; this table is the single coercion point.
_API_TO_SESSION_CHANNEL: dict[str, SessionChannel] = {
    "app": SessionChannel.MOBILE_APP,
    "whatsapp": SessionChannel.WHATSAPP,
    "web": SessionChannel.WEB,
    "call_center": SessionChannel.CALL_CENTER,
}

# Channel -> default agent role. Smart-payments dispatch is intent-driven
# at the agent layer, so the channel alone never routes to it — keeping
# that role explicit prevents an accidental "voice note about my bill"
# from landing on the payments executor.
_CHANNEL_TO_ROLE: dict[SessionChannel, AgentRole] = {
    SessionChannel.MOBILE_APP: AgentRole.CHATBOT,
    SessionChannel.WHATSAPP: AgentRole.CHATBOT,
    SessionChannel.WEB: AgentRole.CHATBOT,
    SessionChannel.CALL_CENTER: AgentRole.CALL_CENTER,
}

_POLICY_TO_DECISION: dict[PolicyDecision, Decision] = {
    PolicyDecision.PASSTHROUGH: Decision.PASSTHROUGH,
    PolicyDecision.FLAG: Decision.FLAG,
    PolicyDecision.ABSTAIN: Decision.ABSTAIN,
    PolicyDecision.ESCALATE: Decision.ESCALATE,
}


def _session_channel_for(api_channel: str) -> SessionChannel:
    """Map a public API channel string to the session-store channel enum."""
    return _API_TO_SESSION_CHANNEL.get(api_channel, SessionChannel.MOBILE_APP)


def _role_for(channel: SessionChannel) -> AgentRole:
    """Pick the default agent role for a channel; chatbot is the safe default."""
    return _CHANNEL_TO_ROLE.get(channel, AgentRole.CHATBOT)


def _decision_for(result: BridgeResult) -> Decision:
    """Project a :class:`BridgeResult` onto the public ``Decision`` enum."""
    if result.escalated:
        return Decision.ESCALATE
    verdict = result.primary.guard_result
    if verdict is None:
        return Decision.PASSTHROUGH
    decision = verdict.outcome.decision
    return _POLICY_TO_DECISION.get(decision, Decision.PASSTHROUGH)


def _confidence_for(result: BridgeResult) -> float:
    """Extract a clamped ``[0, 1]`` confidence from a :class:`BridgeResult`.

    Falls back to 0.0 when no guard verdict is attached (e.g. the agent
    raised before the guard ran). Better to surface "we don't know" than
    to invent a number — downstream metrics treat 0.0 distinctly.
    """
    verdict: GuardResult | None = result.primary.guard_result
    if verdict is None:
        return 0.0
    try:
        c = float(verdict.raw.confidence)
    except (AttributeError, TypeError, ValueError):
        return 0.0
    if c != c:  # NaN
        return 0.0
    return max(0.0, min(1.0, c))


def _audit_decision_for(result: BridgeResult) -> str:
    """Mirror :func:`_decision_for` onto the audit-trail string vocabulary."""
    if result.escalated:
        return AuditDecision.ESCALATE
    verdict = result.primary.guard_result
    if verdict is None:
        return AuditDecision.UNKNOWN
    decision = verdict.outcome.decision
    if isinstance(decision, PolicyDecision):
        return decision.value
    return AuditDecision.UNKNOWN


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    *,
    platform: BridgePlatform | None = None,
    sessions: SessionManager | None = None,
    audit: AuditTrail | None = None,
    model_name: str = "unknown",
) -> Any:
    """Build a FastAPI application wired to the supplied Bridge collaborators.

    Parameters
    ----------
    platform:
        The :class:`~lub.bridge.platform.BridgePlatform` whose registered
        agents should serve ``/query``. When ``None``, the endpoint
        returns a stub response — useful only for local smoke-testing.
    sessions:
        A :class:`~lub.bridge.session.SessionManager` for persisting
        conversation state across turns. When ``None``, an
        :class:`~lub.bridge.session.InMemorySessionStore`-backed
        manager is constructed automatically so every request still
        leaves a session-shaped record behind.
    audit:
        Optional :class:`~lub.bridge.audit.AuditTrail` for BCB 4893 /
        SR 11-7 logging. Strongly recommended in production; absence is
        logged loudly at startup and the ``/compliance`` endpoint marks
        the audit trail as incomplete.
    model_name:
        Stable identifier of the model backing the platform's agents
        (``"gpt-4.1-azure"``, ``"claude-opus-4-7"``, ...). Written
        verbatim onto every audit entry so a regulator can correlate a
        decision back to the model version that produced it.
    """
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError as exc:
        raise ImportError(
            "FastAPI is required for the Bridge API. "
            "Install with: pip install 'llm-uncertainty-banking[api]'"
        ) from exc

    # SessionManager is cheap; default to in-memory so every code path
    # below can rely on it being present without None-checks.
    if sessions is None:
        from lub.connectors.bridge.session import InMemorySessionStore

        sessions = SessionManager(InMemorySessionStore())

    if platform is None:
        _LOG.warning(
            "api.create_app.no_platform",
            detail=(
                "BridgePlatform not supplied; /query will return a stub. "
                "Do not run in production without a configured platform."
            ),
        )
    if audit is None:
        _LOG.warning(
            "api.create_app.no_audit",
            detail=(
                "AuditTrail not supplied; BCB 4893 / SR 11-7 evidence stream "
                "is incomplete. Configure AuditTrail(path=...) before pilot."
            ),
        )

    app = FastAPI(
        title="LUB Bridge API",
        description="Banking AI platform with uncertainty guardrails",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    start_time = time.time()
    custom_agents: dict[str, dict[str, Any]] = {}

    @app.post("/query", response_model=QueryResponse)
    async def query(req: QueryRequest) -> QueryResponse:
        """End-to-end customer query: session -> platform -> guard -> audit."""
        return _handle_query(
            req,
            platform=platform,
            sessions=sessions,
            audit=audit,
            model_name=model_name,
            http_exception=HTTPException,
        )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """Liveness / readiness probe.

        Surfaces the BridgePlatform's per-collaborator health when a
        platform is configured; otherwise reports the registered agent
        count from the stub registry so a Kubernetes probe still sees a
        stable response shape.
        """
        if platform is not None:
            report = platform.health_check()
            status = "ok" if report.healthy else "degraded"
            agents_registered = len(platform.roles)
        else:
            status = "stub"
            agents_registered = len(custom_agents)

        return HealthResponse(
            status=status,
            agents_registered=agents_registered,
            uptime_seconds=round(time.time() - start_time, 1),
        )

    @app.get("/metrics", response_model=MetricsResponse)
    async def metrics() -> MetricsResponse:
        """Bradesco-headline metrics derived from real session state."""
        assert sessions is not None  # narrowed above
        snapshot = sessions.metrics()
        closed = snapshot.resolved + snapshot.escalated
        resolution_rate = (snapshot.resolved / closed) if closed else 0.0
        escalation_rate = (snapshot.escalated / snapshot.total) if snapshot.total else 0.0
        return MetricsResponse(
            total_queries=snapshot.total,
            resolution_rate=resolution_rate,
            escalation_rate=escalation_rate,
            avg_confidence=snapshot.accuracy_rate,
            avg_latency_ms=snapshot.avg_duration_seconds * 1000.0,
            queries_by_channel=dict(snapshot.by_channel),
            queries_by_intent={},
        )

    @app.get("/compliance", response_model=ComplianceResponse)
    async def compliance() -> ComplianceResponse:
        """Compliance evidence summary — BCB 4893, BCBS 239, SR 11-7."""
        audit_complete = audit is not None
        return ComplianceResponse(
            bcb_4893_status="compliant" if audit_complete else "incomplete",
            bcbs_239_status="compliant" if audit_complete else "incomplete",
            sr_11_7_status="compliant" if audit_complete else "incomplete",
            audit_trail_complete=audit_complete,
        )

    @app.get("/agents", response_model=list[AgentInfo])
    async def list_agents() -> list[AgentInfo]:
        """Currently-registered agents, sourced from the platform when available."""
        if platform is not None:
            return [AgentInfo(name=role.value, agent_type=role.value) for role in platform.roles]
        return [
            AgentInfo(name=name, agent_type=info.get("type", "custom"))
            for name, info in custom_agents.items()
        ]

    @app.post("/agents/register", response_model=AgentInfo)
    async def register_agent(req: AgentRegisterRequest) -> AgentInfo:
        """Register an agent stub.

        The REST surface does not have enough context to construct a
        live agent callable (model wiring, credentials, capabilities all
        live in the deployment script). This endpoint therefore records
        the intent for operator visibility but does not mutate the
        BridgePlatform — real registration must go through
        :meth:`BridgePlatform.register_agent` at startup.
        """
        custom_agents[req.name] = {"type": req.agent_type, "config": req.config}
        _LOG.info("api.agent_registered", name=req.name, type=req.agent_type)
        return AgentInfo(name=req.name, agent_type=req.agent_type)

    return app


# ---------------------------------------------------------------------------
# Query orchestration (extracted so it remains independently testable)
# ---------------------------------------------------------------------------


def _handle_query(
    req: QueryRequest,
    *,
    platform: BridgePlatform | None,
    sessions: SessionManager,
    audit: AuditTrail | None,
    model_name: str,
    http_exception: type[HTTPException],
) -> QueryResponse:
    """Run a query end-to-end and translate the result to the API model."""
    customer_id = req.customer_id or f"anon-{uuid.uuid4().hex[:12]}"
    channel = _session_channel_for(req.channel.value)

    # ------------------------------------------------------------------ #
    # 1. Resolve or open a session.
    # ------------------------------------------------------------------ #
    session = None
    if req.session_id:
        try:
            session = sessions.get(req.session_id)
        except SessionNotFoundError:
            session = None
    if session is None:
        session = sessions.start(customer_id=customer_id, channel=channel)

    # ------------------------------------------------------------------ #
    # 2. Append the customer turn. If the session is already closed
    # (resolved/escalated) we surface that explicitly rather than
    # silently starting a new conversation behind the customer's back.
    # ------------------------------------------------------------------ #
    if session.resolved or session.escalated:
        raise http_exception(
            status_code=409,
            detail=(
                f"session {session.session_id!r} is closed "
                f"(resolved={session.resolved}, escalated={session.escalated})"
            ),
        )
    sessions.append(
        session.session_id,
        MessageRole.USER,
        req.query,
        metadata={"channel": req.channel.value, "language": req.language},
    )

    role = _role_for(channel)
    start = time.time()

    # ------------------------------------------------------------------ #
    # 3. Dispatch. If no platform is configured, emit the stub answer so
    # the API stays self-describing during local development.
    # ------------------------------------------------------------------ #
    if platform is None:
        latency_ms = (time.time() - start) * 1000.0
        answer = "Bridge platform is running but no agents are registered yet."
        sessions.append(
            session.session_id,
            MessageRole.ASSISTANT,
            answer,
            metadata={"guard_decision": "unknown", "stub": True},
        )
        return QueryResponse(
            answer=answer,
            confidence=0.0,
            decision=Decision.PASSTHROUGH,
            intent="general",
            agent_used="stub",
            escalated=False,
            latency_ms=round(latency_ms, 2),
            session_id=session.session_id,
            metadata={"stub": True},
        )

    try:
        result = platform.query_with_confidence(req.query, role=role)
    except Exception as exc:  # noqa: BLE001 — surface a structured escalation
        _LOG.error(
            "api.query.dispatch_error",
            error=str(exc),
            error_type=type(exc).__name__,
            session_id=session.session_id,
            role=role.value,
        )
        latency_ms = (time.time() - start) * 1000.0
        sessions.escalate(session.session_id, reason="dispatch_error")
        if audit is not None:
            audit.log_decision(
                AuditEntry(
                    customer_id=customer_id,
                    session_id=session.session_id,
                    query=req.query,
                    response="",
                    confidence=None,
                    decision=AuditDecision.ESCALATE,
                    agent_used=role.value,
                    model_used=model_name,
                    latency_ms=latency_ms,
                    escalated=True,
                    escalation_reason="dispatch_error",
                    extra={
                        "channel": req.channel.value,
                        "error_type": type(exc).__name__,
                    },
                )
            )
        raise http_exception(status_code=502, detail="upstream dispatch failed") from exc

    latency_ms = (time.time() - start) * 1000.0
    confidence = _confidence_for(result)
    decision = _decision_for(result)

    # ------------------------------------------------------------------ #
    # 4. Append the assistant turn and close or keep-open the session.
    # ------------------------------------------------------------------ #
    sessions.append(
        session.session_id,
        MessageRole.ASSISTANT,
        result.primary.answer,
        metadata={
            "guard_decision": decision.value,
            "confidence": confidence,
            "agent_role": result.primary.role.value,
        },
    )

    escalated = bool(result.escalated)
    escalation_reason_str: str | None = None
    if escalated:
        reason = result.escalation_reason
        escalation_reason_str = (
            reason.value if isinstance(reason, EscalationReason) else str(reason or "unknown")
        )
        sessions.escalate(session.session_id, reason=escalation_reason_str)

    # ------------------------------------------------------------------ #
    # 5. Audit log. BCB 4893 §III requires every automated decision be
    # durably recorded; we treat a missing audit trail as a hard
    # configuration warning at app construction and skip silently per-
    # call so a single misconfigured dev environment does not page.
    # ------------------------------------------------------------------ #
    if audit is not None:
        audit.log_decision(
            AuditEntry(
                customer_id=customer_id,
                session_id=session.session_id,
                query=req.query,
                response=result.primary.answer,
                confidence=confidence if result.primary.guard_result is not None else None,
                decision=_audit_decision_for(result),
                agent_used=result.primary.role.value,
                model_used=model_name,
                latency_ms=latency_ms,
                escalated=escalated,
                escalation_reason=escalation_reason_str,
                extra={"channel": req.channel.value, "language": req.language},
            )
        )

    return QueryResponse(
        answer=result.primary.answer,
        confidence=confidence,
        decision=decision,
        intent="general",
        agent_used=result.primary.role.value,
        escalated=escalated,
        latency_ms=round(latency_ms, 2),
        session_id=session.session_id,
        metadata={
            "escalation_reason": escalation_reason_str,
            "model_used": model_name,
        },
    )
