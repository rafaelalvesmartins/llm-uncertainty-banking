# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Operations / observability endpoints.

Endpoints in this router report on the running process — pipeline
metrics, request/error rates, queue depth, per-stage latency budgets,
and SemanticCache stats. They are read-only (with one DELETE on
``/cache``) and only project module-level singletons defined in
``server.py``.

Migrated incrementally from ``server.py`` to ``backend.routers.metrics``;
state still lives in ``server.py`` and is fetched lazily here to break
the circular import. Once ``server.py`` publishes its state via a
dedicated ``backend.state`` module, ``_server`` can become a normal
top-level import.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

try:
    from backend.routers.auth import verify_token
except ImportError:
    from routers.auth import verify_token  # type: ignore[no-redef]

if TYPE_CHECKING:
    from types import ModuleType

router = APIRouter()


def _server() -> ModuleType:
    """Return the ``server`` module via the same fallback dance used by other routers."""
    # Reuse whichever ``server`` module is already loaded so this router's
    # writes and the app's hot-path reads hit the SAME module globals. uvicorn
    # runs ``server:app`` and the tests ``import server`` — both register
    # ``"server"`` in sys.modules. Forcing ``from backend import server`` here
    # would create a divergent second module (runtime state would split).
    import sys
    mod = sys.modules.get("server") or sys.modules.get("backend.server")
    if mod is not None:
        return mod
    try:
        import server  # type: ignore[no-redef]
    except ImportError:
        from backend import server
    return server


@router.get("/metrics")
def metrics() -> dict[str, Any]:
    """Return an aggregate snapshot of all Bridge pipeline activity.

    Bridge hub connection: surfaces the in-memory Metrics aggregator the
    Bridge hub feeds on every ``/query`` (totals, per-intent counts, guard
    decision mix, average confidence and latency) so the UI can render the
    operations dashboard against business targets.
    """
    s = _server()
    return s._METRICS.snapshot()  # type: ignore[no-any-return]


@router.get("/metrics/timeseries")
def metrics_timeseries(max_points: int = 60) -> dict[str, Any]:
    """Down-sampled cumulative decision time series for the dashboard trend chart — a
    real series held in the backend process, so it survives a frontend refresh (resets
    on backend restart, consistent with the in-memory metrics)."""
    s = _server()
    mp = max(2, min(int(max_points), 240))
    points = s._METRICS.timeseries_view(mp)
    return {"n": len(points), "points": points}


@router.get("/stats")
def stats() -> dict[str, Any]:
    """Health watchdog: uptime + rolling RPS/error rate over short windows.

    Bridge hub connection: complements /health (binary alive check) and
    /metrics (per-intent dashboard) with a single-screen operational view —
    how busy is the backend right now, how many errors per minute, what
    was the last error, when did the process start. SR 11-7 Outcome
    Analysis treats sustained 5xx rate as a Tier-1 alert.
    """
    s = _server()
    now = time.time()

    # Snapshot the deques to plain lists before iterating: FastAPI runs sync
    # endpoints in a threadpool, so a concurrent /query appending to these
    # watchdog deques mid-iteration raises "RuntimeError: deque mutated during
    # iteration". list() takes an atomic snapshot; counts may lag by one
    # request, which is fine for a rolling RPS/error view.
    req_ts = list(s._WATCHDOG_REQUEST_TS)
    err_ts = list(s._WATCHDOG_ERROR_TS)

    def count_within(samples: list[float], window_s: float) -> int:
        cutoff = now - window_s
        return sum(1 for ts in samples if ts >= cutoff)

    req_1m = count_within(req_ts, 60.0)
    req_5m = count_within(req_ts, 300.0)
    req_10m = count_within(req_ts, 600.0)
    err_1m = count_within(err_ts, 60.0)
    err_5m = count_within(err_ts, 300.0)
    err_10m = count_within(err_ts, 600.0)
    return {
        "uptime_seconds": round(now - s._PROCESS_START_TS, 1),
        "process_start_ts": s._PROCESS_START_TS,
        "requests_total": len(req_ts),
        "errors_total": len(err_ts),
        "windows": {
            "1m": {
                "requests": req_1m,
                "errors": err_1m,
                "qps": round(req_1m / 60.0, 3),
                "error_rate": round(err_1m / req_1m, 3) if req_1m else 0.0,
            },
            "5m": {
                "requests": req_5m,
                "errors": err_5m,
                "qps": round(req_5m / 300.0, 3),
                "error_rate": round(err_5m / req_5m, 3) if req_5m else 0.0,
            },
            "10m": {
                "requests": req_10m,
                "errors": err_10m,
                "qps": round(req_10m / 600.0, 3),
                "error_rate": round(err_10m / req_10m, 3) if req_10m else 0.0,
            },
        },
        "last_error": s._WATCHDOG_LAST_ERROR,
    }


@router.get("/queue/depth")
def queue_depth() -> dict[str, Any]:
    """Return current Ollama-queue depth (waiters + holder).

    Ollama serializes on a single GPU; concurrent /query calls form an
    invisible queue. This endpoint surfaces that depth so the UI can render
    "you are #N in line" and so client backpressure (HTTP 429) at /query
    has a counterpart for read-only telemetry.
    """
    s = _server()
    return {
        "depth": s._ollama_queue_depth(),
        "max": s._OLLAMA_MAX_QUEUE,
        "breaker_open": s._ollama_breaker_open(),
    }


@router.get("/stages/budgets")
def stages_budgets() -> dict[str, Any]:
    """Per-stage latency vs SLA budget — rolling p50/p95 + breach flag.

    Bridge hub connection: SR 11-7 Outcome Analysis cares not just about
    end-to-end latency (already in /metrics) but about which STAGE is
    burning the budget. This endpoint summarizes the last 500 runs of
    each stage and flags any stage whose p95 has crossed its configured
    budget.
    """
    s = _server()
    stages_out: list[dict[str, Any]] = []
    for name in sorted(s._STAGE_LATENCIES.keys() | s._STAGE_BUDGETS_MS.keys()):
        samples = list(s._STAGE_LATENCIES.get(name, []))
        budget = s._STAGE_BUDGETS_MS.get(name)
        count = len(samples)
        if count == 0:
            stages_out.append(
                {
                    "name": name,
                    "count": 0,
                    "avg_ms": None,
                    "p50_ms": None,
                    "p95_ms": None,
                    "max_ms": None,
                    "budget_ms": budget,
                    "breach": False,
                }
            )
            continue
        p50, p95 = s._percentiles(samples, (0.50, 0.95))
        avg = sum(samples) / count
        stages_out.append(
            {
                "name": name,
                "count": count,
                "avg_ms": round(avg, 2),
                "p50_ms": round(p50, 2),
                "p95_ms": round(p95, 2),
                "max_ms": round(max(samples), 2),
                "budget_ms": budget,
                "breach": (budget is not None and p95 > budget),
            }
        )
    return {
        "stages": stages_out,
        "window": s._STAGE_LATENCY_WINDOW,
        "budgets_source": "static (configured in _STAGE_BUDGETS_MS)",
        "total_breaches": sum(1 for st in stages_out if st["breach"]),
    }


@router.get("/cache")
def cache_stats() -> dict[str, Any]:
    """Stats for the SemanticCache used at Stage 1 of the Bridge pipeline.

    G4 v7 fix: rename ``similarity_threshold`` (misleading — implied real
    vector embeddings) to ``match_strategy`` (honest — describes what the
    cache actually does: normalized-string match with an exact key, no
    embedding model in the demo).
    """
    s = _server()
    stats = s._CACHE.stats()
    avg_cost_per_call = 0.30
    cost_saved_cents = stats["hits"] * avg_cost_per_call
    if "similarity_threshold" in stats:
        threshold = stats.pop("similarity_threshold")
        stats["match_strategy"] = {
            "kind": "normalized_string_match",
            "details": (
                "Cache key = lowercased + stripped + punct-normalized query. "
                "The SemanticCache class accepts a similarity_threshold of "
                f"{threshold} but the demo's FakeBackend has no embedding "
                "model, so matches are exact-on-normalized-key. Paraphrases "
                "will MISS — that's expected for the demo, not a bug."
            ),
            "framework_threshold_unused": threshold,
        }
    return {
        **stats,
        "cost_saved_cents": round(cost_saved_cents, 2),
    }


@router.delete("/cache")
def clear_cache(
    principal: dict[str, Any] | None = Depends(verify_token),
) -> dict[str, int]:
    """Flush the SemanticCache used at Stage 1 of the Bridge pipeline.

    Bridge hub connection: operator action exposed to the dashboard for
    invalidating Bridge's semantic memory (e.g. after a knowledge-base
    update so stale near-matches stop short-circuiting the pipeline).
    """
    s = _server()
    n = s._CACHE.clear()
    return {"cleared": n}


__all__ = ["router"]
