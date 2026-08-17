# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Real-time metrics collector for the Bridge platform.

Aggregates per-query telemetry into the headline numbers Bradesco
reported on the Azure AI Foundry reference page so a deployment can be
monitored against the *same* SLAs the customer story commits to:

* ``retention_rate`` — share of queries kept inside the automated
  channel (no escalation). Bradesco reported **90%**.
* ``accuracy_rate`` — share of guard verdicts that PASSTHROUGH-ed
  (i.e., the model answered with calibrated confidence above the
  configured threshold). Bradesco reported **95%**.
* ``resolution_rate`` — share of queries closed with a non-empty
  answer and no escalation. Bradesco reported **83%** end-to-end.
* ``escalation_rate`` — share of queries routed to a human operator.
* ``avg_confidence`` — running mean of the guard's confidence scores.
* ``avg_latency_ms`` — running mean of agent + guard wall-clock time.
  The 40% call-handling-time reduction Bradesco reported is computed
  against an optional baseline passed at construction time, mirroring
  the convention already used by :mod:`lub.bridge.session`.

Why this lives here
-------------------

BCB 4893 (cyber-resilience), BCBS 239 (risk-data aggregation), and
SR 11-7 (model risk management) all require *measurable* evidence that
an automated banking channel is behaving inside its declared envelope.
This collector is the source-of-truth for that evidence: every
:class:`~lub.bridge.BridgeResult` produced by the platform can be fed
through :meth:`BridgeMetrics.record_query`, and the resulting
:class:`MetricsSnapshot` is what a /metrics endpoint, a Grafana panel,
or a quarterly regulator report draws from.

The class is intentionally transport-agnostic — it does not push to
Prometheus on its own. Callers expose :meth:`to_prometheus` from
whatever HTTP framework they already operate (typically FastAPI), so
the metrics layer carries no networking concerns of its own and stays
trivially unit-testable.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

from lub.connectors.bridge import AgentRole, BridgeResult, EscalationReason
from lub.connectors.bridge.session import Channel
from lub.guard import GuardResult, PolicyDecision

__all__ = [
    "BridgeMetrics",
    "DEFAULT_ACCURACY_TARGET",
    "DEFAULT_LATENCY_P95_MS",
    "DEFAULT_RESOLUTION_TARGET",
    "DEFAULT_RETENTION_TARGET",
    "MetricsSnapshot",
    "SLAMetric",
    "SLATarget",
    "SLAViolation",
]

_LOG = structlog.get_logger("lub.bridge.metrics")


# ---------------------------------------------------------------------------
# SLA constants — Bradesco reference targets
# ---------------------------------------------------------------------------

DEFAULT_RETENTION_TARGET: float = 0.90
"""Headline retention target reported by Bradesco on Azure AI Foundry."""

DEFAULT_ACCURACY_TARGET: float = 0.95
"""Headline guard-pass / response-accuracy target reported by Bradesco."""

DEFAULT_RESOLUTION_TARGET: float = 0.83
"""End-to-end resolution rate reported by Bradesco for Bridge."""

DEFAULT_LATENCY_P95_MS: float = 3000.0
"""Default p95-style ceiling for ``avg_latency_ms``.

Bradesco's customer story does not publish a wall-clock SLA, so this
constant is a conservative placeholder chosen so the SLA check fires
before a user-visible regression slips into production. Override at
:class:`BridgeMetrics` construction time once a real target is set.
"""


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class SLAMetric(StrEnum):
    """Stable identifiers for every metric the SLA checker can flag."""

    RETENTION_RATE = "retention_rate"
    ACCURACY_RATE = "accuracy_rate"
    RESOLUTION_RATE = "resolution_rate"
    AVG_LATENCY_MS = "avg_latency_ms"


@dataclass(frozen=True)
class SLATarget:
    """SLA configuration consumed by :meth:`BridgeMetrics.check_sla`.

    Floors (``retention_rate``, ``accuracy_rate``, ``resolution_rate``)
    are *minimum* acceptable values; the ceiling (``avg_latency_ms``)
    is a *maximum* acceptable value. ``min_samples`` prevents a single
    bad query from triggering a violation before the rolling window has
    enough data to be meaningful — Bradesco serves millions of queries
    daily, so a 100-query warm-up is well inside one minute of traffic.
    """

    retention_rate: float = DEFAULT_RETENTION_TARGET
    accuracy_rate: float = DEFAULT_ACCURACY_TARGET
    resolution_rate: float = DEFAULT_RESOLUTION_TARGET
    avg_latency_ms: float = DEFAULT_LATENCY_P95_MS
    min_samples: int = 100


@dataclass(frozen=True)
class SLAViolation:
    """One breached SLA target.

    Returned by :meth:`BridgeMetrics.check_sla` so callers can ship
    structured alerts (PagerDuty, OpsGenie, etc.) instead of parsing
    log lines.
    """

    metric: SLAMetric
    observed: float
    target: float
    samples: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric.value,
            "observed": float(self.observed),
            "target": float(self.target),
            "samples": int(self.samples),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class MetricsSnapshot:
    """Point-in-time view of every counter the collector maintains.

    Frozen so callers can hand the snapshot to a serializer or send it
    across a thread boundary without worrying about it mutating
    underneath them while the next query is being recorded.
    """

    queries_total: int
    escalations_total: int
    passthroughs_total: int
    guarded_total: int
    retention_rate: float
    accuracy_rate: float
    resolution_rate: float
    escalation_rate: float
    avg_confidence: float
    avg_latency_ms: float
    call_time_reduction: float | None
    queries_by_channel: dict[str, int]
    queries_by_intent: dict[str, int]
    queries_by_role: dict[str, int]
    escalations_by_reason: dict[str, int]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible representation for /metrics and audit export."""
        return {
            "queries_total": int(self.queries_total),
            "escalations_total": int(self.escalations_total),
            "passthroughs_total": int(self.passthroughs_total),
            "guarded_total": int(self.guarded_total),
            "retention_rate": float(self.retention_rate),
            "accuracy_rate": float(self.accuracy_rate),
            "resolution_rate": float(self.resolution_rate),
            "escalation_rate": float(self.escalation_rate),
            "avg_confidence": float(self.avg_confidence),
            "avg_latency_ms": float(self.avg_latency_ms),
            "call_time_reduction": (
                float(self.call_time_reduction) if self.call_time_reduction is not None else None
            ),
            "queries_by_channel": dict(self.queries_by_channel),
            "queries_by_intent": dict(self.queries_by_intent),
            "queries_by_role": dict(self.queries_by_role),
            "escalations_by_reason": dict(self.escalations_by_reason),
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class BridgeMetrics:
    """Thread-safe real-time metrics aggregator for the Bridge platform.

    Parameters
    ----------
    sla:
        SLA targets used by :meth:`check_sla`. Defaults match the
        numbers Bradesco published on the Azure AI Foundry reference
        page; pass a custom :class:`SLATarget` to track a different
        deployment envelope.
    call_center_baseline_ms:
        Pre-AI average call-handling time, in milliseconds, used to
        compute the headline 40% call-time-reduction metric. Pass
        ``None`` to disable the comparison — the snapshot's
        ``call_time_reduction`` will then read ``None`` rather than
        producing a misleading zero.

    Notes
    -----
    The collector is intentionally a *bounded* in-memory aggregator,
    not a time-series store: it keeps running totals so a /metrics
    endpoint can serve them in constant time regardless of how many
    queries have been recorded. Callers that need historical retention
    should scrape :meth:`to_prometheus` into their own TSDB.

    All public methods acquire a single re-entrant lock, so the
    collector is safe to share across the asyncio worker and a
    background scraper goroutine running ``snapshot()`` on a cadence.
    """

    def __init__(
        self,
        sla: SLATarget | None = None,
        *,
        call_center_baseline_ms: float | None = None,
    ) -> None:
        if call_center_baseline_ms is not None and call_center_baseline_ms <= 0:
            raise ValueError("call_center_baseline_ms must be positive when provided")

        self._sla = sla if sla is not None else SLATarget()
        self._baseline_ms = call_center_baseline_ms
        self._lock = threading.RLock()

        # Scalar counters
        self._queries_total = 0
        self._escalations_total = 0
        self._passthroughs_total = 0
        self._guarded_total = 0

        # Running sums (divide at snapshot time)
        self._confidence_sum = 0.0
        self._confidence_count = 0
        self._latency_sum_ms = 0.0
        self._latency_count = 0
        self._call_center_latency_sum_ms = 0.0
        self._call_center_latency_count = 0

        # Labeled counters
        self._by_channel: dict[str, int] = {}
        self._by_intent: dict[str, int] = {}
        self._by_role: dict[str, int] = {}
        self._escalations_by_reason: dict[str, int] = {}

        _LOG.info(
            "bridge.metrics.initialized",
            retention_target=self._sla.retention_rate,
            accuracy_target=self._sla.accuracy_rate,
            resolution_target=self._sla.resolution_rate,
            latency_target_ms=self._sla.avg_latency_ms,
            call_center_baseline_ms=self._baseline_ms,
        )

    # ------------------------------------------------------------------ #
    # Ingest
    # ------------------------------------------------------------------ #

    def record_query(
        self,
        result: BridgeResult,
        *,
        latency_ms: float,
        channel: Channel | str | None = None,
        intent: str | None = None,
    ) -> None:
        """Record one Bridge dispatch.

        Parameters
        ----------
        result:
            The :class:`~lub.bridge.BridgeResult` returned by the
            platform. The collector reads escalation state, role, and
            guard verdict directly off this object so the caller cannot
            silently disagree with the audit trail.
        latency_ms:
            End-to-end wall-clock latency of this query, in
            milliseconds. Negative values are clamped to zero rather
            than raising — instrumentation bugs upstream must never
            crash the metrics path of a banking channel.
        channel:
            Customer-facing surface (``"whatsapp"``, ``"mobile_app"``,
            etc.). Accepts :class:`~lub.bridge.session.Channel` or a
            raw string for callers that have not yet adopted the enum.
            ``None`` is bucketed as ``"unknown"``.
        intent:
            Optional NLU intent label (``"balance_inquiry"``,
            ``"transfer"``, ``"fraud_report"``, ...). Free-form so the
            metrics layer does not force callers to pre-commit to an
            intent taxonomy.

        Notes
        -----
        Failures inside this method never propagate: it wraps the
        bookkeeping in a try/except so a malformed
        :class:`BridgeResult` cannot take the request path down with
        it. Any anomaly is logged at WARNING for ops review.
        """
        try:
            self._record_query_locked(
                result,
                latency_ms=max(0.0, float(latency_ms)),
                channel=_channel_label(channel),
                intent=intent.strip() if isinstance(intent, str) and intent.strip() else "unknown",
            )
        except Exception as exc:  # noqa: BLE001 — metrics must never break the hot path
            _LOG.warning(
                "bridge.metrics.record_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )

    def _record_query_locked(
        self,
        result: BridgeResult,
        *,
        latency_ms: float,
        channel: str,
        intent: str,
    ) -> None:
        with self._lock:
            self._queries_total += 1
            self._latency_sum_ms += latency_ms
            self._latency_count += 1

            role_label = (
                result.primary.role.value
                if isinstance(result.primary.role, AgentRole)
                else str(result.primary.role)
            )
            self._by_role[role_label] = self._by_role.get(role_label, 0) + 1
            self._by_channel[channel] = self._by_channel.get(channel, 0) + 1
            self._by_intent[intent] = self._by_intent.get(intent, 0) + 1

            if channel == Channel.CALL_CENTER.value or role_label == AgentRole.CALL_CENTER.value:
                self._call_center_latency_sum_ms += latency_ms
                self._call_center_latency_count += 1

            if result.escalated:
                self._escalations_total += 1
                reason = (
                    result.escalation_reason.value
                    if isinstance(result.escalation_reason, EscalationReason)
                    else "unknown"
                )
                self._escalations_by_reason[reason] = self._escalations_by_reason.get(reason, 0) + 1

            verdict = result.primary.guard_result
            if isinstance(verdict, GuardResult):
                self._guarded_total += 1
                try:
                    confidence = float(verdict.raw.confidence)
                except Exception:  # noqa: BLE001 — tolerate exotic estimator outputs
                    confidence = float("nan")
                if confidence == confidence:  # NaN check without importing math
                    self._confidence_sum += confidence
                    self._confidence_count += 1
                if verdict.outcome.decision == PolicyDecision.PASSTHROUGH:
                    self._passthroughs_total += 1

    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #

    def snapshot(self) -> MetricsSnapshot:
        """Return a frozen view of every counter."""
        with self._lock:
            total = self._queries_total
            escalated = self._escalations_total
            non_escalated = total - escalated
            resolution_rate = (non_escalated / total) if total else 0.0
            retention_rate = resolution_rate
            escalation_rate = (escalated / total) if total else 0.0
            accuracy_rate = (
                (self._passthroughs_total / self._guarded_total) if self._guarded_total else 0.0
            )
            avg_confidence = (
                (self._confidence_sum / self._confidence_count) if self._confidence_count else 0.0
            )
            avg_latency_ms = (
                (self._latency_sum_ms / self._latency_count) if self._latency_count else 0.0
            )
            call_reduction = self._call_time_reduction_locked()

            return MetricsSnapshot(
                queries_total=total,
                escalations_total=escalated,
                passthroughs_total=self._passthroughs_total,
                guarded_total=self._guarded_total,
                retention_rate=retention_rate,
                accuracy_rate=accuracy_rate,
                resolution_rate=resolution_rate,
                escalation_rate=escalation_rate,
                avg_confidence=avg_confidence,
                avg_latency_ms=avg_latency_ms,
                call_time_reduction=call_reduction,
                queries_by_channel=dict(self._by_channel),
                queries_by_intent=dict(self._by_intent),
                queries_by_role=dict(self._by_role),
                escalations_by_reason=dict(self._escalations_by_reason),
            )

    def check_sla(self, snapshot: MetricsSnapshot | None = None) -> list[SLAViolation]:
        """Compare current metrics against the configured SLA targets.

        Returns an empty list when every metric is inside its envelope
        (the happy path most checks should hit) or when the rolling
        sample count is still below :attr:`SLATarget.min_samples`. The
        sample-count guard prevents a brand-new deployment from
        page-flapping while the first 50 customers are bringing the
        averages out of cold start.
        """
        snap = snapshot if snapshot is not None else self.snapshot()
        violations: list[SLAViolation] = []
        if snap.queries_total < self._sla.min_samples:
            return violations

        if snap.retention_rate < self._sla.retention_rate:
            violations.append(
                SLAViolation(
                    metric=SLAMetric.RETENTION_RATE,
                    observed=snap.retention_rate,
                    target=self._sla.retention_rate,
                    samples=snap.queries_total,
                )
            )
        if (
            snap.guarded_total >= self._sla.min_samples
            and snap.accuracy_rate < self._sla.accuracy_rate
        ):
            violations.append(
                SLAViolation(
                    metric=SLAMetric.ACCURACY_RATE,
                    observed=snap.accuracy_rate,
                    target=self._sla.accuracy_rate,
                    samples=snap.guarded_total,
                )
            )
        if snap.resolution_rate < self._sla.resolution_rate:
            violations.append(
                SLAViolation(
                    metric=SLAMetric.RESOLUTION_RATE,
                    observed=snap.resolution_rate,
                    target=self._sla.resolution_rate,
                    samples=snap.queries_total,
                )
            )
        if snap.avg_latency_ms > self._sla.avg_latency_ms:
            violations.append(
                SLAViolation(
                    metric=SLAMetric.AVG_LATENCY_MS,
                    observed=snap.avg_latency_ms,
                    target=self._sla.avg_latency_ms,
                    samples=snap.queries_total,
                )
            )

        if violations:
            _LOG.warning(
                "bridge.metrics.sla_breached",
                count=len(violations),
                metrics=[v.metric.value for v in violations],
            )
        return violations

    def to_prometheus(self, snapshot: MetricsSnapshot | None = None) -> str:
        """Render the snapshot in Prometheus text exposition format.

        Output uses the v0.0.4 text format expected by ``prometheus``
        and ``vmagent`` scrapers. Counter metrics carry the ``_total``
        suffix; rates and averages are gauges. Labels are emitted with
        single quoted values escaped per the spec.
        """
        snap = snapshot if snapshot is not None else self.snapshot()
        lines: list[str] = []

        # Scalar counters
        _emit_counter(
            lines, "lub_bridge_queries_total", "Total Bridge queries recorded.", snap.queries_total
        )
        _emit_counter(
            lines,
            "lub_bridge_escalations_total",
            "Total Bridge queries escalated to a human.",
            snap.escalations_total,
        )
        _emit_counter(
            lines,
            "lub_bridge_passthroughs_total",
            "Total Bridge queries that passed the uncertainty guard.",
            snap.passthroughs_total,
        )
        _emit_counter(
            lines,
            "lub_bridge_guarded_total",
            "Total Bridge queries that recorded a guard verdict.",
            snap.guarded_total,
        )

        # Headline gauges (Bradesco reference metrics)
        _emit_gauge(
            lines,
            "lub_bridge_retention_rate",
            "Share of queries kept in the automated channel (target 0.90).",
            snap.retention_rate,
        )
        _emit_gauge(
            lines,
            "lub_bridge_accuracy_rate",
            "Share of guard verdicts marked PASSTHROUGH (target 0.95).",
            snap.accuracy_rate,
        )
        _emit_gauge(
            lines,
            "lub_bridge_resolution_rate",
            "Share of queries resolved without escalation (target 0.83).",
            snap.resolution_rate,
        )
        _emit_gauge(
            lines,
            "lub_bridge_escalation_rate",
            "Share of queries routed to a human operator.",
            snap.escalation_rate,
        )
        _emit_gauge(
            lines,
            "lub_bridge_avg_confidence",
            "Running mean of guard confidence scores.",
            snap.avg_confidence,
        )
        _emit_gauge(
            lines,
            "lub_bridge_avg_latency_ms",
            "Running mean of end-to-end query latency (ms).",
            snap.avg_latency_ms,
        )

        if snap.call_time_reduction is not None:
            _emit_gauge(
                lines,
                "lub_bridge_call_time_reduction",
                "Relative reduction in call-center latency vs. pre-AI baseline (target 0.40).",
                snap.call_time_reduction,
            )

        # Labeled gauges
        _emit_labeled(
            lines,
            "lub_bridge_queries_by_channel",
            "Queries grouped by customer channel.",
            "channel",
            snap.queries_by_channel,
        )
        _emit_labeled(
            lines,
            "lub_bridge_queries_by_intent",
            "Queries grouped by NLU intent label.",
            "intent",
            snap.queries_by_intent,
        )
        _emit_labeled(
            lines,
            "lub_bridge_queries_by_role",
            "Queries grouped by Bridge agent role.",
            "role",
            snap.queries_by_role,
        )
        _emit_labeled(
            lines,
            "lub_bridge_escalations_by_reason",
            "Escalations grouped by reason.",
            "reason",
            snap.escalations_by_reason,
        )

        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        """Zero every counter — primarily for tests.

        Production callers should rely on scrape-based deltas rather
        than resetting, because clearing counters mid-flight breaks
        rate() computations in any downstream TSDB.
        """
        with self._lock:
            self._queries_total = 0
            self._escalations_total = 0
            self._passthroughs_total = 0
            self._guarded_total = 0
            self._confidence_sum = 0.0
            self._confidence_count = 0
            self._latency_sum_ms = 0.0
            self._latency_count = 0
            self._call_center_latency_sum_ms = 0.0
            self._call_center_latency_count = 0
            self._by_channel.clear()
            self._by_intent.clear()
            self._by_role.clear()
            self._escalations_by_reason.clear()
        _LOG.info("bridge.metrics.reset")

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _call_time_reduction_locked(self) -> float | None:
        """Compute the 40%-target call-handling-time reduction.

        Returns ``None`` when no baseline was configured or no
        call-center traffic has been observed yet, so callers can
        distinguish "0% reduction" from "no data to compare".
        """
        if self._baseline_ms is None or self._baseline_ms <= 0:
            return None
        if self._call_center_latency_count == 0:
            return None
        avg = self._call_center_latency_sum_ms / self._call_center_latency_count
        return max(0.0, (self._baseline_ms - avg) / self._baseline_ms)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _channel_label(channel: Channel | str | None) -> str:
    """Normalize a channel input into a stable string label."""
    if channel is None:
        return "unknown"
    if isinstance(channel, Channel):
        return channel.value
    label = str(channel).strip()
    return label or "unknown"


def _emit_counter(lines: list[str], name: str, help_text: str, value: int) -> None:
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} counter")
    lines.append(f"{name} {int(value)}")


def _emit_gauge(lines: list[str], name: str, help_text: str, value: float) -> None:
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} gauge")
    lines.append(f"{name} {float(value):.6f}")


def _emit_labeled(
    lines: list[str],
    name: str,
    help_text: str,
    label_name: str,
    samples: Mapping[str, int],
) -> None:
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} gauge")
    if not samples:
        lines.append(f'{name}{{{label_name}="none"}} 0')
        return
    for label_value, count in _sorted_items(samples):
        lines.append(f'{name}{{{label_name}="{_escape_label(label_value)}"}} {int(count)}')


def _sorted_items(samples: Mapping[str, int]) -> Iterable[tuple[str, int]]:
    """Deterministic iteration so Prometheus output diffs are stable."""
    return sorted(samples.items(), key=lambda kv: kv[0])


def _escape_label(value: str) -> str:
    """Escape per Prometheus exposition format: backslash, quote, newline."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
