# Copyright 2026 Rafael Martins Alves — Apache-2.0
"""Runtime observability state — metrics, percentiles, per-stage latency, drift baseline
(decoupling step 5).

Extracted VERBATIM from server.py. Most of it is in-place-mutated or never reassigned
(plain re-exports in server.py); the drift scalars (`_DRIFT_BASELINE`,
`_DRIFT_LAST_AUTO_REBASELINE_AT_QUERY`, `_DRIFT_AUTO_REBASELINE_EVERY`) are rebound here by
`_maybe_capture_baseline` and setattr'd by routers/drift.py on the `server` module, so they
are delegated LIVE via server.py's module-attribute proxy (see server.py EOF + DECOUPLING_PLAN.md).
The semantic cache (`_CACHE`) and the runtime guard/cache toggles stay in server.py with the
/query pipeline.
"""

from __future__ import annotations

import os as _os_for_backend
import time
from collections import deque
from typing import Any


def _percentiles(
    samples: list[float],
    quantiles: tuple[float, ...],
) -> tuple[float, ...]:
    """Linear-interpolation percentiles (numpy-style) over a small sample list.

    Returns one value per requested quantile. Handles empty / single-element
    inputs by collapsing every percentile to that value (or 0.0 if empty),
    so callers don't need a separate branch for cold-start.
    """
    if not samples:
        return tuple(0.0 for _ in quantiles)
    if len(samples) == 1:
        return tuple(samples[0] for _ in quantiles)
    ordered = sorted(samples)
    n = len(ordered)
    out: list[float] = []
    for q in quantiles:
        # rank index in [0, n-1]
        pos = q * (n - 1)
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        out.append(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)
    return tuple(out)


# v15 — per-stage latency tracking. Bounded deques per stage name so the
# /stages/budgets endpoint can return rolling p50/p95 without iterating
# the full audit trail. Updated by the /query path after each pipeline
# run. Stage names match what each PipelineStage carries; budgets are the
# SLA threshold each stage should respect (chosen to flag the LLM tail).
_STAGE_LATENCIES: dict[str, deque[float]] = {}
_STAGE_LATENCY_WINDOW = 500
_STAGE_BUDGETS_MS: dict[str, float] = {
    "dq_input": 50.0,
    "data_governance": 50.0,
    "semantic_cache": 50.0,
    "complexity_router": 25.0,
    "customer_memory": 50.0,
    "rag_retrieval": 100.0,
    "intent_classifier": 50.0,
    # Agent stages — names emitted by the pipeline carry the agent type as
    # a suffix so the budgets must match per-agent. chatbot / smart_payments
    # call the LLM (generous budget); call_center is canned-only (sub-ms).
    "agent": 60_000.0,
    "agent_chatbot": 60_000.0,
    "agent_smart_payments": 60_000.0,
    "agent_call_center": 50.0,
    "uncertainty_guard": 25.0,
    "cache_store": 25.0,
    "dq_output": 50.0,
    "audit_trail": 50.0,
}


def _record_stage_latency(stage_name: str, duration_ms: float) -> None:
    """Append one stage's duration to its rolling window."""
    dq = _STAGE_LATENCIES.get(stage_name)
    if dq is None:
        dq = deque(maxlen=_STAGE_LATENCY_WINDOW)
        _STAGE_LATENCIES[stage_name] = dq
    dq.append(duration_ms)


class Metrics:
    """Aggregates metrics across queries."""

    def __init__(self) -> None:
        self.queries_total = 0
        self.queries_by_intent: dict[str, int] = {}
        self.confidences: list[float] = []
        self.decisions: dict[str, int] = {
            "PASSTHROUGH": 0,
            "FLAG": 0,
            "REASK": 0,
            "ESCALATE": 0,
        }
        self.latencies_ms: list[float] = []
        # Rolling time series of cumulative decision counts, appended per query, so the
        # dashboard trend survives a frontend refresh (held in the backend process;
        # resets on restart, consistent with the rest of the in-memory metrics).
        self.timeseries: deque[dict[str, Any]] = deque(maxlen=1000)

    def record(
        self,
        intent: str,
        confidence: float,
        decision: str,
        latency_ms: float,
    ) -> None:
        """Record one query's outcome into the Bridge metrics aggregator.

        Bridge hub connection: called at the end of Stage 9 on every
        ``/query`` so the hub's in-memory Metrics object stays in sync with
        what the pipeline actually produced — feeding the ``/metrics``
        snapshot the dashboard polls.

        Args:
            intent: Final intent label assigned by the IntentClassifier.
            confidence: Confidence score that drove the guard decision.
            decision: UncertaintyGuard verdict (PASSTHROUGH/FLAG/REASK/ESCALATE).
            latency_ms: End-to-end pipeline latency in milliseconds.
        """
        self.queries_total += 1
        self.queries_by_intent[intent] = self.queries_by_intent.get(intent, 0) + 1
        self.confidences.append(confidence)
        self.decisions[decision] = self.decisions.get(decision, 0) + 1
        self.latencies_ms.append(latency_ms)
        self.timeseries.append({
            "ts": time.time(),
            "queries_total": self.queries_total,
            "PASSTHROUGH": self.decisions.get("PASSTHROUGH", 0),
            "FLAG": self.decisions.get("FLAG", 0),
            "REASK": self.decisions.get("REASK", 0),
            "ESCALATE": self.decisions.get("ESCALATE", 0),
        })

    def timeseries_view(self, max_points: int = 60) -> list[dict[str, Any]]:
        """Down-sampled cumulative decision time series (the most recent point is
        always included) — backs the dashboard trend chart."""
        pts = list(self.timeseries)
        if len(pts) <= max_points:
            return pts
        step = len(pts) / max_points
        out = [pts[int(i * step)] for i in range(max_points)]
        out[-1] = pts[-1]
        return out

    def snapshot(self) -> dict[str, Any]:
        """Compute the aggregate dashboard view over all recorded queries.

        Bridge hub connection: produces the payload returned by ``/metrics``
        — totals, per-intent counts, decision mix, mean confidence/latency,
        plus the business targets the Bridge program is measured against.

        Returns:
            Dict with totals, derived rates (resolution/escalation), the
            full per-intent and per-decision breakdowns, and the configured
            target thresholds for resolution/retention/accuracy.
        """
        avg_conf = sum(self.confidences) / len(self.confidences) if self.confidences else 0.0
        avg_lat = sum(self.latencies_ms) / len(self.latencies_ms) if self.latencies_ms else 0.0
        # v10 P3: real ops view — auditors and SRE want p50/p95/p99, not avg.
        # SR 11-7 talks about model performance bounds; an avg hides the tail
        # where Ollama re-loads or RAG hits cold index. Use linear-interp
        # percentile (numpy-style) so the values match what Grafana shows.
        p50_lat, p95_lat, p99_lat = _percentiles(self.latencies_ms, (0.50, 0.95, 0.99))
        passthrough = self.decisions.get("PASSTHROUGH", 0)
        escalate = self.decisions.get("ESCALATE", 0)
        resolution_rate = passthrough / self.queries_total if self.queries_total else 0.0
        escalation_rate = escalate / self.queries_total if self.queries_total else 0.0
        return {
            "queries_total": self.queries_total,
            "avg_confidence": round(avg_conf, 3),
            "avg_latency_ms": round(avg_lat, 1),
            "p50_latency_ms": round(p50_lat, 1),
            "p95_latency_ms": round(p95_lat, 1),
            "p99_latency_ms": round(p99_lat, 1),
            "resolution_rate": round(resolution_rate, 3),
            "escalation_rate": round(escalation_rate, 3),
            # Copies, not the live dicts — FastAPI serializes after the handler
            # returns, and a concurrent /query inserting a first-seen key
            # mid-iteration raises "dictionary changed size during iteration".
            "queries_by_intent": dict(self.queries_by_intent),
            "decisions": dict(self.decisions),
            "target_resolution": 0.83,
            "target_retention": 0.90,
            "target_accuracy": 0.95,
        }


_METRICS = Metrics()


# v10 P3 — drift detection. Captures a baseline snapshot of the intent
# distribution (taken automatically once `_DRIFT_BASELINE_AT_QUERIES`
# queries have been seen, or manually via POST /drift/baseline) and
# exposes per-intent deltas against the current rolling distribution.
# Useful for SR 11-7 model-monitoring: a sudden shift in the intent mix
# is the cheapest possible warning that the upstream channel changed
# (marketing push, holiday traffic, prompt-injection campaign, …).
_DRIFT_BASELINE_AT_QUERIES = 50
# v15: periodic auto-rebaseline. When set > 0, the baseline rolls forward
# every N queries so the "current vs baseline" delta tracks a moving
# window rather than the original first-50 forever. Disabled (0) by
# default; ops can enable via env BRIDGE_DRIFT_AUTO_REBASELINE_EVERY=200
# to compare current activity vs the last 200-query window.
_DRIFT_AUTO_REBASELINE_EVERY = int(
    _os_for_backend.environ.get("BRIDGE_DRIFT_AUTO_REBASELINE_EVERY", "0")
)
_DRIFT_BASELINE: dict[str, Any] | None = None
_DRIFT_LAST_AUTO_REBASELINE_AT_QUERY = 0


def _snapshot_for_baseline(source: str) -> dict[str, Any]:
    """Build a baseline payload from the live Metrics state."""
    return {
        "captured_at": time.time(),
        "queries_total": _METRICS.queries_total,
        "queries_by_intent": dict(_METRICS.queries_by_intent),
        "decisions": dict(_METRICS.decisions),
        "avg_latency_ms": (
            sum(_METRICS.latencies_ms) / len(_METRICS.latencies_ms)
            if _METRICS.latencies_ms
            else 0.0
        ),
        "source": source,
    }


def _maybe_capture_baseline() -> None:
    """Auto-capture or roll the baseline forward as queries flow."""
    global _DRIFT_BASELINE, _DRIFT_LAST_AUTO_REBASELINE_AT_QUERY
    # First-ever auto-capture.
    if _DRIFT_BASELINE is None and _METRICS.queries_total >= _DRIFT_BASELINE_AT_QUERIES:
        _DRIFT_BASELINE = _snapshot_for_baseline("auto")
        _DRIFT_LAST_AUTO_REBASELINE_AT_QUERY = _METRICS.queries_total
        return
    # Periodic roll-forward (opt-in, env-configured).
    if (
        _DRIFT_BASELINE is not None
        and _DRIFT_AUTO_REBASELINE_EVERY > 0
        and _METRICS.queries_total - _DRIFT_LAST_AUTO_REBASELINE_AT_QUERY
        >= _DRIFT_AUTO_REBASELINE_EVERY
    ):
        _DRIFT_BASELINE = _snapshot_for_baseline("auto-rolling")
        _DRIFT_LAST_AUTO_REBASELINE_AT_QUERY = _METRICS.queries_total


__all__ = [
    '_percentiles',
    '_STAGE_LATENCIES',
    '_STAGE_LATENCY_WINDOW',
    '_STAGE_BUDGETS_MS',
    '_record_stage_latency',
    'Metrics',
    '_METRICS',
    '_DRIFT_BASELINE_AT_QUERIES',
    '_DRIFT_AUTO_REBASELINE_EVERY',
    '_DRIFT_BASELINE',
    '_DRIFT_LAST_AUTO_REBASELINE_AT_QUERY',
    '_snapshot_for_baseline',
    '_maybe_capture_baseline',
]
