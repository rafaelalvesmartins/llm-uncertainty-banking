# Copyright 2026 Rafael Martins Alves — Apache-2.0
"""Prometheus metrics exporter — Track D (scale), ADDITIVE + INERT.

Mirrors the fields tracked by ``state.runtime.Metrics`` as Prometheus
instruments so a Grafana/Prometheus stack can scrape them without touching
the running demo's in-process aggregator.

NOT wired into the app: ``record_query`` must be called explicitly from the
pipeline; ``routers/observability.py`` exposes the scrape endpoint but is
not mounted in ``server.py``.

Instruments
-----------
bridge_query_latency_seconds (Histogram)
    End-to-end pipeline latency.  Mirrors ``Metrics.latencies_ms`` (stored
    as ms; converted to seconds on record).  Labelled by ``decision`` and
    ``intent`` so Grafana can slice p95 per decision type.

bridge_queries_total (Counter)
    One counter-per-call carrying ``decision``, ``intent``, and ``channel``
    labels.  Mirrors ``Metrics.queries_total`` / ``Metrics.queries_by_intent``
    / ``Metrics.decisions`` in a single instrument.

bridge_resolution_rate_approx (Gauge)
    Approximate ratio of PASSTHROUGH decisions to total; updated on every
    ``record_query`` call.  Mirrors ``Metrics.snapshot()["resolution_rate"]``.

bridge_escalation_rate_approx (Gauge)
    Approximate ratio of ESCALATE decisions to total.  Mirrors
    ``Metrics.snapshot()["escalation_rate"]``.

All instruments live on a private ``CollectorRegistry`` so this module can be
imported safely in test contexts without polluting the default registry or
conflicting with other prometheus-client users in the same process.
"""

from __future__ import annotations

import threading

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# ---------------------------------------------------------------------------
# Private registry — isolates Track-D instruments from any other prometheus
# users in the same process and from the default registry in tests.
# ---------------------------------------------------------------------------
REGISTRY = CollectorRegistry(auto_describe=True)

# Histogram: latency in seconds, buckets tuned for the Bridge pipeline
# (10 ms fast cache hit → ~2 s LLM tail; dense around the sub-100 ms
# path where most decisions land, sparser above the 1 s agent ceiling).
_LATENCY_HISTOGRAM = Histogram(
    "bridge_query_latency_seconds",
    "End-to-end Bridge pipeline latency in seconds.",
    labelnames=["decision", "intent"],
    buckets=(
        0.010,  # 10 ms  — semantic-cache hit / canned call-center reply
        0.025,  # 25 ms
        0.050,  # 50 ms  — complexity-router + light guard path
        0.075,
        0.100,  # 100 ms — RAG retrieval p50
        0.150,
        0.200,  # 200 ms — intent-classifier + guard full path
        0.300,
        0.500,  # 500 ms — Ollama chatbot fast response
        0.750,
        1.000,  # 1 s    — Ollama p95 under moderate load
        1.500,
        2.000,  # 2 s    — Ollama tail / smart-payments complex query
    ),
    registry=REGISTRY,
)

# Counter: one observation per query, labelled for slicing by decision, intent,
# and originating channel.  Mirrors decisions dict + queries_by_intent + total.
_QUERIES_COUNTER = Counter(
    "bridge_queries_total",
    "Total Bridge pipeline queries processed.",
    labelnames=["decision", "intent", "channel"],
    registry=REGISTRY,
)

# Gauges: derived rates updated incrementally; avoid needing a full snapshot
# for the scrape while staying reasonably close to the in-process values.
_RESOLUTION_RATE = Gauge(
    "bridge_resolution_rate_approx",
    "Approximate fraction of queries resolved as PASSTHROUGH (updated per query).",
    registry=REGISTRY,
)

_ESCALATION_RATE = Gauge(
    "bridge_escalation_rate_approx",
    "Approximate fraction of queries escalated (updated per query).",
    registry=REGISTRY,
)

# ---------------------------------------------------------------------------
# Internal running totals for rate computation — kept minimal, no deque.
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_total: int = 0
_passthrough: int = 0
_escalate: int = 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_query(
    *,
    latency_ms: float,
    decision: str,
    intent: str,
    channel: str = "api",
) -> None:
    """Record one pipeline result into the Prometheus instruments.

    This is the single hook the query pipeline would call.  It is NOT wired
    anywhere yet — callers must import and invoke it explicitly.

    Args:
        latency_ms: End-to-end pipeline latency in milliseconds (matches
            the unit stored in ``Metrics.latencies_ms``; converted to
            seconds before being observed on the histogram).
        decision: UncertaintyGuard verdict — one of PASSTHROUGH / FLAG /
            REASK / ESCALATE (mirrors ``Metrics.decisions`` keys).
        intent: Intent label from the IntentClassifier (mirrors
            ``Metrics.queries_by_intent`` keys).
        channel: Originating channel (e.g. ``"api"``, ``"chatbot"``,
            ``"call_center"``).  Defaults to ``"api"`` when not supplied.
    """
    global _total, _passthrough, _escalate

    _LATENCY_HISTOGRAM.labels(decision=decision, intent=intent).observe(
        latency_ms / 1000.0
    )
    _QUERIES_COUNTER.labels(decision=decision, intent=intent, channel=channel).inc()

    with _lock:
        _total += 1
        if decision == "PASSTHROUGH":
            _passthrough += 1
        elif decision == "ESCALATE":
            _escalate += 1
        resolution = _passthrough / _total
        escalation = _escalate / _total

    _RESOLUTION_RATE.set(resolution)
    _ESCALATION_RATE.set(escalation)


def metrics_text() -> tuple[bytes, str]:
    """Render all registered instruments in Prometheus text format.

    Returns:
        A ``(body, content_type)`` tuple suitable for returning directly
        from a FastAPI ``Response``.  The content type is
        ``CONTENT_TYPE_LATEST`` from ``prometheus_client``.
    """
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


__all__ = [
    "REGISTRY",
    "record_query",
    "metrics_text",
]
