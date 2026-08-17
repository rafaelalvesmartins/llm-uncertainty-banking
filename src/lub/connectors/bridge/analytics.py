# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Behavioural analytics engine for the Bridge platform.

Where :mod:`lub.bridge.metrics` answers "is the platform healthy *right
now*?", this module answers "how are customers actually using it?".
It is the source-of-truth for the longitudinal KPIs Bradesco published
on the Azure AI Foundry reference page:

* **90% retention** ? share of customers who keep using the automated
  channel from one period to the next (Bradesco's headline metric).
* **83% end-to-end resolution** ? share of queries closed without a
  human handoff.

Reports
-------

Four read-only views feed compliance dashboards, ops paging, and the
quarterly regulator narrative:

* :meth:`BridgeAnalytics.retention_funnel` ? new ? active ? retained ?
  churned cohort breakdown over a configurable window.
* :meth:`BridgeAnalytics.intent_distribution` ? relative volume per
  NLU intent label inside the window.
* :meth:`BridgeAnalytics.confidence_histogram` ? 10-bin distribution of
  guard confidence scores; the tail below 0.5 is what calibration work
  targets next.
* :meth:`BridgeAnalytics.peak_hours` ? hour-of-day workload profile,
  used by the call-center capacity planner.

Why this lives in :mod:`lub.bridge`
-----------------------------------

Bradesco's banking workflows are regulated under BCB 4893
(cyber-resilience), BCBS 239 (risk-data aggregation), and SR 11-7
(model risk management). All three demand *reproducible, customer-level
evidence* that an automated channel is behaving inside its declared
envelope ? the per-event ledger this engine maintains is exactly that
evidence. The engine is intentionally transport-agnostic: callers feed
it :class:`~lub.bridge.BridgeResult` objects from the request path and
serialize the resulting reports to whatever sink they prefer (REST,
Prometheus textfile, audit lake).

Design notes
------------

* The engine keeps a bounded in-memory ledger (configurable cap,
  default 100_000 events). This is small enough to fit on a single
  pilot node yet large enough to cover a multi-day rolling window for
  pre-prod analysis. For long-horizon retention math a downstream TSDB
  or warehouse is expected to take over.
* All public methods acquire a single re-entrant lock, so the engine
  is safe to share across the asyncio worker, a scheduled report job,
  and an interactive notebook running ad-hoc queries.
* The engine never raises on a malformed event ? banking telemetry
  must never take the hot path down. Anomalies are logged at WARNING.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from lub.connectors.bridge import AgentRole, BridgeResult, EscalationReason
from lub.connectors.bridge.session import Channel
from lub.guard import GuardResult, PolicyDecision

__all__ = [
    "AnalyticsEvent",
    "BridgeAnalytics",
    "ConfidenceBucket",
    "DEFAULT_HISTOGRAM_BINS",
    "DEFAULT_LEDGER_CAPACITY",
    "DEFAULT_RESOLUTION_TARGET",
    "DEFAULT_RETENTION_TARGET",
    "FunnelReport",
    "HourStats",
    "Period",
]

_LOG = structlog.get_logger("lub.bridge.analytics")


# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------


DEFAULT_RETENTION_TARGET: float = 0.90
"""Headline retention KPI reported by Bradesco on Azure AI Foundry."""

DEFAULT_RESOLUTION_TARGET: float = 0.83
"""End-to-end resolution KPI reported by Bradesco on Azure AI Foundry."""

DEFAULT_LEDGER_CAPACITY: int = 100_000
"""Maximum in-memory events kept before the oldest is evicted.

Sized for a single pilot node: at ~10 queries/second the deque covers
roughly 2.7 hours of traffic, which is plenty for the rolling-window
reports this module emits. For longer horizons defer to a TSDB.
"""

DEFAULT_HISTOGRAM_BINS: int = 10
"""Default bin count for :meth:`BridgeAnalytics.confidence_histogram`.

Ten equal-width bins over ``[0, 1]`` is the resolution most calibration
dashboards expect and matches the granularity of the Bradesco reference
materials.
"""


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Period:
    """Half-open ``[start, end)`` time window for an analytics query.

    Frozen so callers can hand a period across threads or cache it as
    a dict key without worrying about mutation. The ``contains`` helper
    is convenience for filter loops below; the half-open convention
    keeps adjacent periods from double-counting boundary events.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(
                f"Period.end ({self.end.isoformat()}) precedes start ({self.start.isoformat()})"
            )

    @property
    def duration(self) -> timedelta:
        """Length of the window."""
        return self.end - self.start

    def contains(self, ts: datetime) -> bool:
        """Whether ``ts`` falls inside ``[start, end)``."""
        return self.start <= ts < self.end

    def shift(self, delta: timedelta) -> Period:
        """Return a new period shifted by ``delta`` (used for prior windows)."""
        return Period(start=self.start + delta, end=self.end + delta)

    def to_dict(self) -> dict[str, str]:
        """Serialize the period to ISO-8601 strings for Bridge report payloads.

        Used by every Bridge analytics report that embeds a window
        descriptor (funnel, REST API responses, audit-lake exports) so
        downstream consumers receive a transport-agnostic, JSON-safe
        representation rather than raw ``datetime`` objects.

        Returns
        -------
        dict[str, str]
            ``{"start": <iso8601>, "end": <iso8601>}``.
        """
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass(frozen=True)
class AnalyticsEvent:
    """One Bridge dispatch, frozen for the ledger.

    Carries only the dimensions the reports below need, so a million
    events fit comfortably in memory. Customer identity is *opaque* ?
    callers should pass a hashed/pseudonymous id, never raw PII, per
    LGPD Art. 12 (anonymised data) and BCB 4893 data-handling rules.
    """

    timestamp: datetime
    customer_id: str
    role: AgentRole
    channel: str
    intent: str
    escalated: bool
    escalation_reason: EscalationReason | None
    decision: PolicyDecision | None
    confidence: float | None
    latency_ms: float


@dataclass(frozen=True)
class FunnelReport:
    """Cohort breakdown for the new ? active ? retained ? churned funnel.

    * ``new_customers`` ? customers whose first observed event in the
      ledger lands inside ``period``.
    * ``active_customers`` ? customers who produced at least one event
      during ``period`` (regardless of when they first appeared).
    * ``retained_customers`` ? active in both ``period`` and the
      immediately-preceding equal-length window.
    * ``churned_customers`` ? active in the prior window but absent
      from ``period``.

    ``retention_rate`` is the Bradesco-style headline: of the customers
    who *could* have come back (active in the prior window), what share
    actually did? It is reported as ``0.0`` when the prior window had
    no traffic, so a brand-new pilot does not surface a misleading 100%
    on day one.

    ``resolution_rate`` is the share of queries resolved without
    escalation during ``period``; Bradesco's published target is 0.83.
    """

    period: Period
    prior_period: Period
    new_customers: int
    active_customers: int
    retained_customers: int
    churned_customers: int
    queries_total: int
    queries_resolved: int
    retention_rate: float
    resolution_rate: float

    def meets_retention_target(self, target: float = DEFAULT_RETENTION_TARGET) -> bool:
        """Whether the observed retention clears the configured KPI."""
        return self.retention_rate >= target

    def meets_resolution_target(self, target: float = DEFAULT_RESOLUTION_TARGET) -> bool:
        """Whether the observed resolution clears the configured KPI."""
        return self.resolution_rate >= target

    def to_dict(self) -> dict[str, Any]:
        """Serialize the funnel report for Bridge dashboards and audit exports.

        The Bridge REST API, the Prometheus textfile exporter, and the
        regulator-facing audit lake all consume this payload, so the
        method also emits the two ``meets_*_target`` booleans inline ?
        downstream sinks should never need to recompute KPI gates from
        the raw rates.

        Returns
        -------
        dict[str, Any]
            Cohort counts, KPI rates, and gate decisions, with nested
            :class:`Period` windows already serialized.
        """
        return {
            "period": self.period.to_dict(),
            "prior_period": self.prior_period.to_dict(),
            "new_customers": int(self.new_customers),
            "active_customers": int(self.active_customers),
            "retained_customers": int(self.retained_customers),
            "churned_customers": int(self.churned_customers),
            "queries_total": int(self.queries_total),
            "queries_resolved": int(self.queries_resolved),
            "retention_rate": float(self.retention_rate),
            "resolution_rate": float(self.resolution_rate),
            "meets_retention_target": self.meets_retention_target(),
            "meets_resolution_target": self.meets_resolution_target(),
        }


@dataclass(frozen=True)
class ConfidenceBucket:
    """One bin of the confidence histogram.

    ``lower`` is inclusive, ``upper`` is exclusive except for the final
    bin where ``upper == 1.0`` is inclusive, so a perfectly-confident
    response (score == 1.0) is never silently dropped.
    """

    lower: float
    upper: float
    count: int
    share: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize one histogram bucket for Bridge calibration dashboards.

        Bridge's calibration tooling consumes a list of these dicts to
        plot the guard-confidence distribution; the explicit ``float``
        / ``int`` coercions guarantee the payload survives a JSON round
        trip regardless of the numeric type the engine accumulated.

        Returns
        -------
        dict[str, Any]
            Bin edges (``lower``, ``upper``), ``count`` of events in
            the bin, and ``share`` of total scored events.
        """
        return {
            "lower": float(self.lower),
            "upper": float(self.upper),
            "count": int(self.count),
            "share": float(self.share),
        }


@dataclass(frozen=True)
class HourStats:
    """Workload profile for a single hour-of-day slot.

    ``hour`` is in ``[0, 23]`` interpreted in UTC. ``escalation_rate``
    is the share of queries in this slot that were routed to a human,
    so capacity planners can see *when* the bot most needs backup ?
    the call-center surface follows a clear afternoon peak in Brazil.
    """

    hour: int
    query_count: int
    escalation_count: int
    escalation_rate: float
    avg_latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize one hour-of-day slot for the Bridge capacity planner.

        Feeds the call-center shift planner and the ops dashboard that
        watches afternoon-peak escalation pressure on the Bridge hub.
        Returned as plain scalars so it slots straight into a JSON
        response or a Prometheus textfile without further coercion.

        Returns
        -------
        dict[str, Any]
            UTC ``hour`` plus the slot's query volume, escalation
            counts/rate, and average end-to-end latency in ms.
        """
        return {
            "hour": int(self.hour),
            "query_count": int(self.query_count),
            "escalation_count": int(self.escalation_count),
            "escalation_rate": float(self.escalation_rate),
            "avg_latency_ms": float(self.avg_latency_ms),
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class BridgeAnalytics:
    """Thread-safe behavioural analytics engine for the Bridge platform.

    Parameters
    ----------
    capacity:
        Maximum events retained in the bounded in-memory ledger. The
        oldest event is evicted once this is exceeded. Pass ``0`` to
        disable the cap (unbounded growth ? only safe in tests).
    retention_target:
        KPI used by :attr:`FunnelReport.meets_retention_target`.
        Defaults to Bradesco's published 0.90 retention number.
    resolution_target:
        KPI used by :attr:`FunnelReport.meets_resolution_target`.
        Defaults to Bradesco's published 0.83 resolution number.

    Notes
    -----
    The engine is *append-only* from the caller's perspective:
    :meth:`record_event` is the one ingest point, and every report is
    computed from a snapshot of the ledger taken under the lock so
    concurrent recording cannot tear a report mid-iteration.
    """

    def __init__(
        self,
        *,
        capacity: int = DEFAULT_LEDGER_CAPACITY,
        retention_target: float = DEFAULT_RETENTION_TARGET,
        resolution_target: float = DEFAULT_RESOLUTION_TARGET,
    ) -> None:
        if capacity < 0:
            raise ValueError("capacity must be non-negative")
        if not 0.0 <= retention_target <= 1.0:
            raise ValueError("retention_target must be in [0, 1]")
        if not 0.0 <= resolution_target <= 1.0:
            raise ValueError("resolution_target must be in [0, 1]")

        self._capacity = capacity
        self._retention_target = retention_target
        self._resolution_target = resolution_target
        self._lock = threading.RLock()
        self._events: deque[AnalyticsEvent] = deque(maxlen=capacity) if capacity > 0 else deque()

        _LOG.info(
            "bridge.analytics.initialized",
            capacity=capacity,
            retention_target=retention_target,
            resolution_target=resolution_target,
        )

    # ------------------------------------------------------------------ #
    # Ingest
    # ------------------------------------------------------------------ #

    def record_query(
        self,
        result: BridgeResult,
        *,
        customer_id: str,
        latency_ms: float,
        channel: Channel | str | None = None,
        intent: str | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """Append one Bridge dispatch to the ledger.

        Parameters
        ----------
        result:
            The :class:`~lub.bridge.BridgeResult` returned by the
            platform.
        customer_id:
            Opaque, pseudonymous customer identifier. The engine never
            inspects the value beyond using it as a dict key, so
            callers should hash any PII upstream (LGPD Art. 12).
        latency_ms:
            End-to-end wall-clock latency of this query. Negative
            values are clamped to zero ? instrumentation glitches must
            not poison the ledger.
        channel:
            Customer-facing surface. Accepts a :class:`Channel` enum or
            a raw string; ``None`` is bucketed as ``"unknown"``.
        intent:
            Optional NLU intent label. Free-form so the engine does
            not force callers to commit to a taxonomy.
        timestamp:
            Override for the event time. Defaults to ``now(UTC)``;
            tests use this to seed deterministic windows.

        Notes
        -----
        Wraps the bookkeeping in a try/except so a malformed result
        never crashes the request path. Anomalies are logged at WARNING.
        """
        try:
            event = self._build_event(
                result,
                customer_id=customer_id,
                latency_ms=latency_ms,
                channel=channel,
                intent=intent,
                timestamp=timestamp,
            )
        except Exception as exc:  # noqa: BLE001 ? telemetry must not break the hot path
            _LOG.warning(
                "bridge.analytics.record_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return

        with self._lock:
            self._events.append(event)

    def record_event(self, event: AnalyticsEvent) -> None:
        """Append a pre-built :class:`AnalyticsEvent` directly.

        Useful for replaying a historical ledger (e.g., loaded from an
        audit lake during a regulator inquiry) without rebuilding the
        original :class:`BridgeResult` payloads.
        """
        with self._lock:
            self._events.append(event)

    def _build_event(
        self,
        result: BridgeResult,
        *,
        customer_id: str,
        latency_ms: float,
        channel: Channel | str | None,
        intent: str | None,
        timestamp: datetime | None,
    ) -> AnalyticsEvent:
        if not customer_id or not isinstance(customer_id, str):
            raise ValueError("customer_id must be a non-empty string")

        ts = timestamp if timestamp is not None else datetime.now(UTC)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        role = (
            result.primary.role
            if isinstance(result.primary.role, AgentRole)
            else AgentRole(str(result.primary.role))
        )

        verdict = result.primary.guard_result
        decision: PolicyDecision | None = None
        confidence: float | None = None
        if isinstance(verdict, GuardResult):
            outcome = getattr(verdict, "outcome", None) or getattr(verdict, "policy_outcome", None)
            decision = getattr(outcome, "decision", None) if outcome is not None else None
            raw = getattr(verdict, "raw", None)
            if raw is not None:
                try:
                    score = float(raw.confidence)
                except Exception:  # noqa: BLE001 ? exotic estimator outputs
                    score = float("nan")
                if score == score and 0.0 <= score <= 1.0:
                    confidence = score

        return AnalyticsEvent(
            timestamp=ts,
            customer_id=customer_id,
            role=role,
            channel=_channel_label(channel),
            intent=_intent_label(intent),
            escalated=bool(result.escalated),
            escalation_reason=(
                result.escalation_reason
                if isinstance(result.escalation_reason, EscalationReason)
                else None
            ),
            decision=decision,
            confidence=confidence,
            latency_ms=max(0.0, float(latency_ms)),
        )

    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #

    def __len__(self) -> int:
        """Number of events currently held in the ledger."""
        with self._lock:
            return len(self._events)

    def snapshot_events(self, period: Period | None = None) -> tuple[AnalyticsEvent, ...]:
        """Return a frozen snapshot of the ledger, optionally filtered.

        Exposed so callers can run ad-hoc reports the built-ins don't
        cover (e.g., a notebook investigating a specific intent) without
        risking concurrent mutation.
        """
        with self._lock:
            if period is None:
                return tuple(self._events)
            return tuple(e for e in self._events if period.contains(e.timestamp))

    def retention_funnel(self, period: Period) -> FunnelReport:
        """Compute the new ? active ? retained ? churned funnel.

        The prior window is implicit: it has the same duration as
        ``period`` and ends exactly when ``period`` starts, so the two
        partition the recent past cleanly. This matches how Bradesco
        publishes its 90% retention figure (week-over-week and
        month-over-month).
        """
        prior = period.shift(-period.duration)

        with self._lock:
            events = tuple(self._events)

        current_customers: set[str] = set()
        prior_customers: set[str] = set()
        first_seen: dict[str, datetime] = {}
        current_queries = 0
        resolved_queries = 0

        for ev in events:
            if ev.customer_id not in first_seen or ev.timestamp < first_seen[ev.customer_id]:
                first_seen[ev.customer_id] = ev.timestamp
            if period.contains(ev.timestamp):
                current_customers.add(ev.customer_id)
                current_queries += 1
                if not ev.escalated:
                    resolved_queries += 1
            elif prior.contains(ev.timestamp):
                prior_customers.add(ev.customer_id)

        retained = current_customers & prior_customers
        churned = prior_customers - current_customers
        new = {
            cid
            for cid in current_customers
            if period.contains(first_seen.get(cid, period.end))
            and not prior.contains(first_seen.get(cid, period.end))
        }

        retention_rate = (len(retained) / len(prior_customers)) if prior_customers else 0.0
        resolution_rate = (resolved_queries / current_queries) if current_queries else 0.0

        report = FunnelReport(
            period=period,
            prior_period=prior,
            new_customers=len(new),
            active_customers=len(current_customers),
            retained_customers=len(retained),
            churned_customers=len(churned),
            queries_total=current_queries,
            queries_resolved=resolved_queries,
            retention_rate=retention_rate,
            resolution_rate=resolution_rate,
        )

        _LOG.info(
            "bridge.analytics.retention_funnel",
            period=period.to_dict(),
            active_customers=report.active_customers,
            retained_customers=report.retained_customers,
            retention_rate=report.retention_rate,
            resolution_rate=report.resolution_rate,
            meets_retention=report.meets_retention_target(self._retention_target),
            meets_resolution=report.meets_resolution_target(self._resolution_target),
        )
        return report

    def intent_distribution(self, period: Period) -> dict[str, int]:
        """Count queries grouped by NLU intent label within ``period``.

        Returned dict is ordered by count descending so a caller
        rendering a chart can take the top-N straight off the iterator.
        """
        counts: dict[str, int] = {}
        for ev in self._iter_period(period):
            counts[ev.intent] = counts.get(ev.intent, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    def confidence_histogram(
        self,
        period: Period,
        *,
        bins: int = DEFAULT_HISTOGRAM_BINS,
    ) -> list[ConfidenceBucket]:
        """Bin guard confidence scores into ``bins`` equal-width buckets.

        Bins span ``[0, 1]`` with the final bin inclusive at the upper
        edge so a 1.0 score lands in the last bucket rather than being
        silently dropped. Events without a numeric confidence score
        (e.g., the guard raised) are skipped ? they show up in the
        intent/funnel reports instead.
        """
        if bins <= 0:
            raise ValueError("bins must be a positive integer")

        edges = [i / bins for i in range(bins + 1)]
        counts = [0] * bins
        total = 0
        for ev in self._iter_period(period):
            if ev.confidence is None:
                continue
            idx = min(int(ev.confidence * bins), bins - 1)
            counts[idx] += 1
            total += 1

        buckets: list[ConfidenceBucket] = []
        for i in range(bins):
            share = (counts[i] / total) if total else 0.0
            buckets.append(
                ConfidenceBucket(
                    lower=edges[i],
                    upper=edges[i + 1],
                    count=counts[i],
                    share=share,
                )
            )
        return buckets

    def peak_hours(self, period: Period | None = None) -> list[HourStats]:
        """Aggregate workload by hour-of-day (UTC), sorted by volume desc.

        Hours with zero traffic are omitted so the returned list is a
        compact view of *where* the load actually is. Each entry's
        ``escalation_rate`` and ``avg_latency_ms`` come from that hour's
        events only, making this the single report the call-center
        capacity planner needs to right-size operator shifts.
        """
        per_hour_count: dict[int, int] = {}
        per_hour_escalations: dict[int, int] = {}
        per_hour_latency_sum: dict[int, float] = {}

        for ev in self._iter_period(period):
            hour = ev.timestamp.astimezone(UTC).hour
            per_hour_count[hour] = per_hour_count.get(hour, 0) + 1
            per_hour_latency_sum[hour] = per_hour_latency_sum.get(hour, 0.0) + ev.latency_ms
            if ev.escalated:
                per_hour_escalations[hour] = per_hour_escalations.get(hour, 0) + 1

        stats: list[HourStats] = []
        for hour, count in per_hour_count.items():
            escalations = per_hour_escalations.get(hour, 0)
            avg_latency = per_hour_latency_sum.get(hour, 0.0) / count if count else 0.0
            stats.append(
                HourStats(
                    hour=hour,
                    query_count=count,
                    escalation_count=escalations,
                    escalation_rate=(escalations / count) if count else 0.0,
                    avg_latency_ms=avg_latency,
                )
            )
        stats.sort(key=lambda s: (-s.query_count, s.hour))
        return stats

    # ------------------------------------------------------------------ #
    # Maintenance
    # ------------------------------------------------------------------ #

    def reset(self) -> None:
        """Drop every event in the ledger ? primarily for tests."""
        with self._lock:
            self._events.clear()
        _LOG.info("bridge.analytics.reset")

    @property
    def retention_target(self) -> float:
        """Configured retention KPI floor (default ``0.90``)."""
        return self._retention_target

    @property
    def resolution_target(self) -> float:
        """Configured resolution KPI floor (default ``0.83``)."""
        return self._resolution_target

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _iter_period(self, period: Period | None) -> Iterator[AnalyticsEvent]:
        """Yield ledger events, optionally filtered to ``period``.

        Iterates over a snapshot rather than the live deque so a
        concurrent :meth:`record_query` cannot mutate the structure
        mid-loop.
        """
        with self._lock:
            snapshot = tuple(self._events)
        if period is None:
            yield from snapshot
            return
        for ev in snapshot:
            if period.contains(ev.timestamp):
                yield ev


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


def _intent_label(intent: str | None) -> str:
    """Normalize an intent input into a stable string label."""
    if not isinstance(intent, str):
        return "unknown"
    label = intent.strip()
    return label or "unknown"


def _ensure_iterable(events: Iterable[AnalyticsEvent]) -> tuple[AnalyticsEvent, ...]:
    """Materialize an iterable of events into a tuple snapshot."""
    return tuple(events)
