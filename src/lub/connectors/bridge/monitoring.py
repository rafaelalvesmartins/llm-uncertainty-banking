# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Real-time health monitoring for the Bradesco Bridge platform.

The Bridge platform serves the three customer-facing surfaces Bradesco
published on the Azure AI Foundry reference page (chatbot, call center,
Smart Payments). Each of those surfaces sits in the path of regulated
banking workflows, so a *measurable* statement about platform health —
not just request-level metrics — is a hard requirement for BCB 4893
(cyber-resilience), BCBS 239 (risk-data aggregation), and SR 11-7
(model risk management).

This module composes the three existing health signals already produced
by lower layers into a single dashboard view:

* **Agent readiness** — every :class:`~lub.bridge.AgentRole` expected by
  the deployment is registered with the :class:`~lub.bridge.BridgePlatform`.
* **Backend availability** — the LLM-agnostic :class:`~lub.bridge.router.BridgeRouter`
  reports at least one healthy (enabled, not in circuit-breaker cooldown)
  backend per required capability.
* **Operational envelope** — the :class:`~lub.bridge.metrics.BridgeMetrics`
  rolling counters are inside their configured SLA, the running confidence
  distribution sits above a configurable floor, and the escalation rate is
  below a configurable ceiling (the complement of the Bradesco 90% retention
  number, by default).

The monitor produces three artifacts:

* :meth:`BridgeMonitor.health_check` — a structured :class:`HealthStatus`
  with one :class:`ComponentHealth` per checked subsystem. This is what a
  Kubernetes ``/healthz`` probe or an external uptime checker reads.
* :meth:`BridgeMonitor.alert_if_degraded` — a list of :class:`Alert`
  objects ready to be shipped to PagerDuty / OpsGenie. Every emitted alert
  is also written through ``structlog`` so the SIEM has a parallel
  audit-grade copy.
* :meth:`BridgeMonitor.dashboard_data` — a JSON-friendly snapshot for a
  Grafana panel or an internal status page.

The class intentionally carries no networking concerns of its own. It is
a *pure aggregator* — the caller is responsible for exposing the result
over HTTP, pushing it to a webhook, or scraping it on a cadence.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

from lub.connectors.bridge import AgentRole, BridgePlatform
from lub.connectors.bridge.metrics import BridgeMetrics, MetricsSnapshot, SLAMetric, SLAViolation
from lub.connectors.bridge.router import BridgeRouter, Capability

__all__ = [
    "Alert",
    "AlertSeverity",
    "BridgeMonitor",
    "ComponentHealth",
    "DEFAULT_CONFIDENCE_FLOOR",
    "DEFAULT_ESCALATION_CEILING",
    "HealthState",
    "HealthStatus",
]

_LOG = structlog.get_logger("lub.bridge.monitoring")


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

DEFAULT_CONFIDENCE_FLOOR: float = 0.60
"""Minimum acceptable rolling-mean guard confidence.

Below this floor the Bridge response stream is statistically dominated
by low-confidence verdicts, which usually points to one of:

* Calibration drift on the underlying estimator.
* A capability mismatch (e.g., vision queries hitting a text-only
  backend) producing systematically uncertain answers.
* A prompt-template regression after a deployment.

Banking deployments should err conservative — Bradesco's own reference
numbers imply the production system runs comfortably above 0.80 — but
0.60 is set as the default *alerting* floor so the page doesn't flap
during cold-start. Override at construction time per deployment.
"""

DEFAULT_ESCALATION_CEILING: float = 0.10
"""Maximum tolerable rolling escalation rate (= 1 - retention floor).

Bradesco published a 90% retention target on the Azure AI Foundry
reference page; the complementary view is "at most 10% of queries leave
the automated channel". Configurable so an experimental surface can
adopt a different envelope without forcing a code change.
"""


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class HealthState(StrEnum):
    """Three-state platform health classification.

    * ``HEALTHY`` — every checked subsystem is inside its envelope.
    * ``DEGRADED`` — at least one warning-level signal is firing, but
      the platform is still serving customer traffic correctly. Page
      ops during business hours, not at 03:00.
    * ``UNHEALTHY`` — a critical-level signal is firing (e.g., no
      healthy backend at all, or the platform has no registered agents).
      Page ops immediately.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class AlertSeverity(StrEnum):
    """Severity ladder for :class:`Alert` objects.

    Maps cleanly onto PagerDuty's ``info``/``warning``/``critical``
    severities so a webhook receiver does not need a translation layer.
    """

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ComponentHealth:
    """Per-subsystem health record.

    ``detail`` is a free-form dict so each check can attach the exact
    measurement that drove its verdict — e.g., the list of missing roles,
    the per-backend cooldown remaining, or the observed-vs-target SLA
    deltas. Treat it as opaque from outside the monitor; never key off
    of specific field names in alerting rules without first looking at
    the component name.
    """

    name: str
    state: HealthState
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this component to a JSON-friendly dict for the dashboard payload.

        Bridge's :meth:`BridgeMonitor.dashboard_data` aggregator calls this
        on every component so the resulting structure can be shipped to a
        Grafana panel or status page without a separate marshaller.

        Returns
        -------
        dict[str, Any]
            Keys ``name``, ``state`` (string value of the enum), ``summary``,
            and a defensive copy of ``detail`` so callers cannot mutate the
            frozen dataclass through the returned reference.
        """
        return {
            "name": self.name,
            "state": self.state.value,
            "summary": self.summary,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class HealthStatus:
    """Aggregated platform health, returned by :meth:`BridgeMonitor.health_check`.

    The ``state`` field is the *worst* state observed across components:
    a single ``UNHEALTHY`` component drags the overall state down to
    ``UNHEALTHY`` even when every other check is green. This is the
    appropriate fail-fast semantics for a banking platform — a partially
    broken authentication path is not a "degraded" condition, it is a
    full outage from the customer's point of view.
    """

    state: HealthState
    components: tuple[ComponentHealth, ...]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def healthy(self) -> bool:
        """Return whether the Bridge platform is fully healthy.

        Convenience accessor used by Kubernetes-style ``/healthz`` probes
        and the Bridge dashboard payload to avoid a string comparison
        against :attr:`HealthState.HEALTHY` at every call site.

        Returns
        -------
        bool
            ``True`` when ``state`` is :attr:`HealthState.HEALTHY`,
            ``False`` for ``DEGRADED`` or ``UNHEALTHY``.
        """
        return self.state is HealthState.HEALTHY

    def to_dict(self) -> dict[str, Any]:
        """Serialize the aggregated status for the Bridge dashboard / probe payload.

        Used by :meth:`BridgeMonitor.dashboard_data` and by any HTTP layer
        the operator wraps around the monitor to expose health over
        ``/healthz``.

        Returns
        -------
        dict[str, Any]
            Keys ``state``, ``healthy`` (the boolean shortcut), the
            per-component list produced via :meth:`ComponentHealth.to_dict`,
            and the ISO-8601 ``timestamp`` of when the snapshot was taken.
        """
        return {
            "state": self.state.value,
            "healthy": self.healthy,
            "components": [c.to_dict() for c in self.components],
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class Alert:
    """A single emitted alert.

    Carries enough structured context that an alerting webhook can
    deduplicate and group alerts without parsing the message string.
    ``observed`` / ``target`` are populated for numeric checks (SLA
    violations, confidence floor, escalation ceiling) and left ``None``
    for binary checks (missing agent, no healthy backend) — receivers
    should branch on ``component`` rather than relying on the numeric
    fields being non-null.
    """

    severity: AlertSeverity
    component: str
    message: str
    observed: float | None = None
    target: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Serialize this alert for the Bridge alerting webhook and SIEM log.

        :meth:`BridgeMonitor.alert_if_degraded` calls this both when shipping
        alerts to PagerDuty/OpsGenie and when writing the parallel
        ``structlog`` audit record required by BCB 4893 reviewers, so the
        shape must stay stable across releases.

        Returns
        -------
        dict[str, Any]
            Keys ``severity``, ``component``, ``message``, the numeric
            ``observed``/``target`` (coerced to ``float`` or ``None``), a
            defensive copy of ``detail``, and the ISO-8601 ``timestamp``.
        """
        return {
            "severity": self.severity.value,
            "component": self.component,
            "message": self.message,
            "observed": (float(self.observed) if self.observed is not None else None),
            "target": (float(self.target) if self.target is not None else None),
            "detail": dict(self.detail),
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------


class BridgeMonitor:
    """Real-time aggregator for Bridge platform health and alerting.

    Parameters
    ----------
    platform:
        The live :class:`~lub.bridge.BridgePlatform` whose agent registry
        is inspected for role coverage.
    metrics:
        The :class:`~lub.bridge.metrics.BridgeMetrics` instance fed by the
        request path. Its rolling snapshot drives every numeric check
        (SLA violations, confidence floor, escalation ceiling).
    router:
        Optional :class:`~lub.bridge.router.BridgeRouter`. When supplied,
        a backend-availability check is included; when ``None``, that
        check is skipped (some deployments wire the agents straight to
        a single backend and do not own a router).
    required_roles:
        Roles that *must* be registered for the platform to be considered
        healthy. Defaults to every member of :class:`~lub.bridge.AgentRole`
        — the three Bradesco-published surfaces. Pass a narrower iterable
        when running a partial deployment (e.g., chatbot-only pilot).
    required_capabilities:
        Capabilities that must each have at least one healthy backend
        behind them. Defaults to an empty tuple, which means "any healthy
        backend at all is sufficient". Set this when the deployment
        requires e.g. ``Capability.VISION`` for the Smart Payments
        surface and the absence of a vision backend should fail the
        health check.
    confidence_floor:
        Minimum acceptable rolling-mean guard confidence. See
        :data:`DEFAULT_CONFIDENCE_FLOOR`.
    escalation_ceiling:
        Maximum tolerable rolling escalation rate. See
        :data:`DEFAULT_ESCALATION_CEILING`.

    Notes
    -----
    The monitor is stateless beyond its construction parameters and is
    safe to share across threads provided the supplied ``platform``,
    ``metrics``, and ``router`` are themselves thread-safe (which the
    Bridge module's defaults are).
    """

    def __init__(
        self,
        platform: BridgePlatform,
        metrics: BridgeMetrics,
        router: BridgeRouter | None = None,
        *,
        required_roles: Iterable[AgentRole] | None = None,
        required_capabilities: Iterable[Capability] = (),
        confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
        escalation_ceiling: float = DEFAULT_ESCALATION_CEILING,
    ) -> None:
        if not 0.0 <= confidence_floor <= 1.0:
            raise ValueError("confidence_floor must be in [0.0, 1.0]")
        if not 0.0 <= escalation_ceiling <= 1.0:
            raise ValueError("escalation_ceiling must be in [0.0, 1.0]")

        self._platform = platform
        self._metrics = metrics
        self._router = router
        self._required_roles: tuple[AgentRole, ...] = tuple(
            required_roles if required_roles is not None else AgentRole
        )
        self._required_capabilities: tuple[Capability, ...] = tuple(required_capabilities)
        self._confidence_floor = float(confidence_floor)
        self._escalation_ceiling = float(escalation_ceiling)

        _LOG.info(
            "bridge.monitoring.initialized",
            required_roles=[r.value for r in self._required_roles],
            required_capabilities=[c.value for c in self._required_capabilities],
            confidence_floor=self._confidence_floor,
            escalation_ceiling=self._escalation_ceiling,
            router_attached=self._router is not None,
        )

    # ------------------------------------------------------------------ #
    # Health
    # ------------------------------------------------------------------ #

    def health_check(self) -> HealthStatus:
        """Run every configured check and return the aggregated status.

        Each individual check is wrapped in a try/except so that a
        malformed snapshot, a router lookup error, or any other transient
        failure inside one subsystem cannot mask the rest of the report.
        A check that raises is itself rendered as a ``DEGRADED``
        component carrying the exception class and message, so reviewers
        always see something rather than a silently dropped signal.
        """
        components: list[ComponentHealth] = []
        snapshot = self._safe_snapshot()

        components.append(self._check_agents())
        if self._router is not None:
            components.append(self._check_backends())
        components.append(self._check_sla(snapshot))
        components.append(self._check_confidence(snapshot))
        components.append(self._check_escalation_rate(snapshot))

        overall = _worst_state(c.state for c in components)
        status = HealthStatus(state=overall, components=tuple(components))

        _LOG.info(
            "bridge.monitoring.health_check",
            state=status.state.value,
            components={c.name: c.state.value for c in components},
        )
        return status

    def alert_if_degraded(self) -> list[Alert]:
        """Translate the current health status into an Alert list.

        ``HEALTHY`` components contribute no alerts. ``DEGRADED``
        components emit a ``WARNING`` alert; ``UNHEALTHY`` components
        emit a ``CRITICAL`` alert. Every emitted alert is logged through
        ``structlog`` at the corresponding level so a SIEM ingesting the
        log stream sees the same events as the alerting webhook — this
        parallel-write pattern is what BCB 4893 reviewers expect when
        auditing the alerting path.
        """
        status = self.health_check()
        alerts: list[Alert] = []
        for component in status.components:
            alert = _component_to_alert(component)
            if alert is None:
                continue
            alerts.append(alert)
            payload = alert.to_dict()
            if alert.severity is AlertSeverity.CRITICAL:
                _LOG.error("bridge.monitoring.alert", **payload)
            else:
                _LOG.warning("bridge.monitoring.alert", **payload)
        return alerts

    def dashboard_data(self) -> dict[str, Any]:
        """JSON-friendly snapshot suitable for a status page or Grafana.

        Bundles the current health status, the live metrics snapshot,
        the per-backend health view (when a router is attached), and the
        derived alert list. The shape is deliberately stable so a
        downstream renderer can be cached against it without per-release
        breakage.
        """
        status = self.health_check()
        snapshot = self._safe_snapshot()
        alerts = [
            alert.to_dict()
            for component in status.components
            for alert in (_component_to_alert(component),)
            if alert is not None
        ]
        return {
            "status": status.to_dict(),
            "metrics": snapshot.to_dict() if snapshot is not None else None,
            "backends": self._router.health() if self._router is not None else None,
            "alerts": alerts,
            "config": {
                "required_roles": [r.value for r in self._required_roles],
                "required_capabilities": [c.value for c in self._required_capabilities],
                "confidence_floor": self._confidence_floor,
                "escalation_ceiling": self._escalation_ceiling,
            },
        }

    # ------------------------------------------------------------------ #
    # Individual checks
    # ------------------------------------------------------------------ #

    def _check_agents(self) -> ComponentHealth:
        try:
            registered = set(self._platform.roles)
            missing = sorted(r.value for r in self._required_roles if r not in registered)
            if not missing:
                return ComponentHealth(
                    name="agents",
                    state=HealthState.HEALTHY,
                    summary=f"{len(registered)} agent(s) registered",
                    detail={"registered": sorted(r.value for r in registered)},
                )
            return ComponentHealth(
                name="agents",
                state=HealthState.UNHEALTHY,
                summary=f"{len(missing)} required role(s) missing",
                detail={
                    "missing": missing,
                    "registered": sorted(r.value for r in registered),
                },
            )
        except Exception as exc:  # noqa: BLE001 — monitoring must not crash
            return _exception_component("agents", exc)

    def _check_backends(self) -> ComponentHealth:
        assert self._router is not None  # narrowed by caller
        try:
            health = self._router.health()
            if not health:
                return ComponentHealth(
                    name="backends",
                    state=HealthState.UNHEALTHY,
                    summary="no backends registered with router",
                    detail={},
                )

            healthy = {name: info for name, info in health.items() if info.get("healthy")}
            if not healthy:
                return ComponentHealth(
                    name="backends",
                    state=HealthState.UNHEALTHY,
                    summary="all registered backends are unhealthy",
                    detail={"backends": health},
                )

            missing_caps: list[str] = []
            for cap in self._required_capabilities:
                if not any(cap.value in info.get("capabilities", []) for info in healthy.values()):
                    missing_caps.append(cap.value)

            if missing_caps:
                return ComponentHealth(
                    name="backends",
                    state=HealthState.UNHEALTHY,
                    summary=f"no healthy backend for required capabilities: {missing_caps}",
                    detail={"missing_capabilities": missing_caps, "backends": health},
                )

            unhealthy = [name for name, info in health.items() if not info.get("healthy")]
            if unhealthy:
                return ComponentHealth(
                    name="backends",
                    state=HealthState.DEGRADED,
                    summary=f"{len(unhealthy)} backend(s) in cooldown",
                    detail={"unhealthy": sorted(unhealthy), "backends": health},
                )

            return ComponentHealth(
                name="backends",
                state=HealthState.HEALTHY,
                summary=f"{len(healthy)} backend(s) healthy",
                detail={"backends": health},
            )
        except Exception as exc:  # noqa: BLE001 — monitoring must not crash
            return _exception_component("backends", exc)

    def _check_sla(self, snapshot: MetricsSnapshot | None) -> ComponentHealth:
        try:
            if snapshot is None:
                return ComponentHealth(
                    name="sla",
                    state=HealthState.DEGRADED,
                    summary="metrics snapshot unavailable",
                    detail={},
                )
            violations = self._metrics.check_sla(snapshot)
            if not violations:
                return ComponentHealth(
                    name="sla",
                    state=HealthState.HEALTHY,
                    summary="all SLAs within bounds",
                    detail={
                        "queries_total": snapshot.queries_total,
                        "avg_latency_ms": snapshot.avg_latency_ms,
                        "retention_rate": snapshot.retention_rate,
                        "accuracy_rate": snapshot.accuracy_rate,
                    },
                )
            state = (
                HealthState.UNHEALTHY
                if any(
                    v.metric is SLAMetric.AVG_LATENCY_MS or v.observed == 0.0 for v in violations
                )
                else HealthState.DEGRADED
            )
            return ComponentHealth(
                name="sla",
                state=state,
                summary=f"{len(violations)} SLA violation(s)",
                detail={"violations": [v.to_dict() for v in violations]},
            )
        except Exception as exc:  # noqa: BLE001 — monitoring must not crash
            return _exception_component("sla", exc)

    def _check_confidence(self, snapshot: MetricsSnapshot | None) -> ComponentHealth:
        try:
            if snapshot is None or snapshot.guarded_total == 0:
                return ComponentHealth(
                    name="confidence",
                    state=HealthState.HEALTHY,
                    summary="no guarded queries observed yet",
                    detail={"floor": self._confidence_floor},
                )
            observed = float(snapshot.avg_confidence)
            if observed < self._confidence_floor:
                return ComponentHealth(
                    name="confidence",
                    state=HealthState.DEGRADED,
                    summary=f"avg confidence {observed:.3f} below floor {self._confidence_floor:.3f}",
                    detail={
                        "observed": observed,
                        "floor": self._confidence_floor,
                        "guarded_total": snapshot.guarded_total,
                    },
                )
            return ComponentHealth(
                name="confidence",
                state=HealthState.HEALTHY,
                summary=f"avg confidence {observed:.3f} above floor {self._confidence_floor:.3f}",
                detail={
                    "observed": observed,
                    "floor": self._confidence_floor,
                    "guarded_total": snapshot.guarded_total,
                },
            )
        except Exception as exc:  # noqa: BLE001 — monitoring must not crash
            return _exception_component("confidence", exc)

    def _check_escalation_rate(self, snapshot: MetricsSnapshot | None) -> ComponentHealth:
        try:
            if snapshot is None or snapshot.queries_total == 0:
                return ComponentHealth(
                    name="escalation",
                    state=HealthState.HEALTHY,
                    summary="no queries observed yet",
                    detail={"ceiling": self._escalation_ceiling},
                )
            observed = float(snapshot.escalation_rate)
            if observed > self._escalation_ceiling:
                return ComponentHealth(
                    name="escalation",
                    state=HealthState.DEGRADED,
                    summary=f"escalation rate {observed:.3f} above ceiling {self._escalation_ceiling:.3f}",
                    detail={
                        "observed": observed,
                        "ceiling": self._escalation_ceiling,
                        "queries_total": snapshot.queries_total,
                        "escalations_total": snapshot.escalations_total,
                    },
                )
            return ComponentHealth(
                name="escalation",
                state=HealthState.HEALTHY,
                summary=f"escalation rate {observed:.3f} below ceiling {self._escalation_ceiling:.3f}",
                detail={
                    "observed": observed,
                    "ceiling": self._escalation_ceiling,
                    "queries_total": snapshot.queries_total,
                    "escalations_total": snapshot.escalations_total,
                },
            )
        except Exception as exc:  # noqa: BLE001 — monitoring must not crash
            return _exception_component("escalation", exc)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _safe_snapshot(self) -> MetricsSnapshot | None:
        try:
            return self._metrics.snapshot()
        except Exception as exc:  # noqa: BLE001 — monitoring must not crash
            _LOG.warning(
                "bridge.monitoring.snapshot_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_STATE_RANK: dict[HealthState, int] = {
    HealthState.HEALTHY: 0,
    HealthState.DEGRADED: 1,
    HealthState.UNHEALTHY: 2,
}


def _worst_state(states: Iterable[HealthState]) -> HealthState:
    """Return the most severe state in ``states`` (HEALTHY when empty)."""
    worst = HealthState.HEALTHY
    for state in states:
        if _STATE_RANK[state] > _STATE_RANK[worst]:
            worst = state
    return worst


def _exception_component(name: str, exc: BaseException) -> ComponentHealth:
    """Render a failed check as a DEGRADED component rather than dropping it."""
    _LOG.warning(
        "bridge.monitoring.check_failed",
        component=name,
        error_type=type(exc).__name__,
        error=str(exc),
    )
    return ComponentHealth(
        name=name,
        state=HealthState.DEGRADED,
        summary=f"check raised {type(exc).__name__}",
        detail={"error_type": type(exc).__name__, "error": str(exc)},
    )


def _component_to_alert(component: ComponentHealth) -> Alert | None:
    """Translate one component into an Alert, or ``None`` when healthy."""
    if component.state is HealthState.HEALTHY:
        return None

    severity = (
        AlertSeverity.CRITICAL
        if component.state is HealthState.UNHEALTHY
        else AlertSeverity.WARNING
    )
    observed, target = _extract_observed_target(component)
    return Alert(
        severity=severity,
        component=component.name,
        message=component.summary,
        observed=observed,
        target=target,
        detail=dict(component.detail),
    )


def _extract_observed_target(component: ComponentHealth) -> tuple[float | None, float | None]:
    """Best-effort extraction of numeric observed/target from a component.

    Components produced by this module embed a small set of well-known
    keys (``observed``, ``floor``, ``ceiling``, ``violations``); this
    helper pulls the most informative pair so the resulting Alert can
    be deduplicated and graphed without re-parsing free-form summaries.
    """
    detail = component.detail
    observed_raw = detail.get("observed")
    target_raw = detail.get("floor", detail.get("ceiling"))

    # SLA component carries a list of violations; promote the first one
    # so the alert has a numeric handle (the rest stay in `detail`).
    if observed_raw is None and isinstance(detail.get("violations"), list):
        violations = detail["violations"]
        if violations:
            first: dict[str, Any] | SLAViolation = violations[0]
            if isinstance(first, dict):
                observed_raw = first.get("observed")
                target_raw = first.get("target")

    observed = _coerce_float(observed_raw)
    target = _coerce_float(target_raw)
    return observed, target


def _coerce_float(value: Any) -> float | None:
    """Convert a value to ``float`` when possible, otherwise ``None``."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
