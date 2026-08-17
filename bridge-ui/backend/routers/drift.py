# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Drift monitoring endpoints (SR 11-7 model monitoring).

Three endpoints expose the per-intent distribution drift signal:

* ``GET  /drift``                — current vs baseline TV-distance + per-intent deltas
* ``POST /drift/baseline``       — manually capture the current snapshot as baseline
* ``POST /drift/auto-rebaseline``— enable/disable periodic auto-rebaselining

The ``POST`` endpoints mutate module-level globals on ``server.py``
(``_DRIFT_BASELINE``, ``_DRIFT_LAST_AUTO_REBASELINE_AT_QUERY``,
``_DRIFT_AUTO_REBASELINE_EVERY``). Mutation is performed via ``setattr``
on the server module so the change is visible to every other reader of
those names, exactly as ``global ...`` did inside ``server.py``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException

try:
    from backend.routers.auth import verify_token
except ImportError:
    from routers.auth import verify_token  # type: ignore[no-redef]

if TYPE_CHECKING:
    from types import ModuleType

router = APIRouter()


def _server() -> ModuleType:
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


def _audit_drift_event(s: ModuleType, event: str, operator: str, **detail: Any) -> None:
    """Record a drift state change on the SAME audit hash-chain the /query path uses,
    so a single-operator rebaseline / cadence change is dated + attributed (SR 11-7).
    Best-effort: never block the control if the audit sink hiccups."""
    try:
        s._audit_append(
            {
                "ts": time.time(),
                "event": event,
                "intent": "drift",
                "decision": "APPLIED",
                "operator": operator or "unknown",
                "channel": "console",
                **detail,
            }
        )
    except Exception as e:  # noqa: BLE001 — audit is best-effort, never block the control
        print(f"[drift] audit append failed ({event}): {e}", flush=True)


@router.get("/drift")
def drift() -> dict[str, Any]:
    """Compare current intent / decision distribution against the baseline.

    Bridge hub connection: SR 11-7 model-monitoring view. The baseline is
    captured automatically after the first ``_DRIFT_BASELINE_AT_QUERIES``
    queries (or via POST /drift/baseline). The response lists per-intent
    percentage-point deltas, the top-3 movers, and a simple total-variation
    distance (sum of absolute deltas / 2). TV-distance > 0.20 is a strong
    drift signal worth surfacing on the dashboard.
    """
    s = _server()
    snap = s._METRICS.snapshot()
    cur_total = snap.get("queries_total", 0) or 0
    if s._DRIFT_BASELINE is None:
        return {
            "baseline_captured": False,
            "current_queries": cur_total,
            "baseline_at": s._DRIFT_BASELINE_AT_QUERIES,
            "remaining_until_auto_capture": max(
                0, s._DRIFT_BASELINE_AT_QUERIES - cur_total
            ),
            "note": (
                "The baseline is captured automatically after the first "
                f"{s._DRIFT_BASELINE_AT_QUERIES} queries, or call "
                "POST /drift/baseline to capture it now."
            ),
        }
    base_total = s._DRIFT_BASELINE["queries_total"] or 1
    base_by_intent: dict[str, int] = s._DRIFT_BASELINE.get("queries_by_intent", {}) or {}
    cur_by_intent: dict[str, int] = snap.get("queries_by_intent", {}) or {}
    all_intents = sorted(set(base_by_intent) | set(cur_by_intent))
    deltas: list[dict[str, Any]] = []
    tv = 0.0
    for it in all_intents:
        base_pct = (base_by_intent.get(it, 0) / base_total) * 100
        cur_pct = (cur_by_intent.get(it, 0) / cur_total * 100) if cur_total else 0.0
        delta_pp = cur_pct - base_pct
        tv += abs(delta_pp) / 100.0
        deltas.append(
            {
                "intent": it,
                "baseline_pct": round(base_pct, 2),
                "current_pct": round(cur_pct, 2),
                "delta_pp": round(delta_pp, 2),
            }
        )
    tv_distance = round(tv / 2.0, 3)
    movers = sorted(deltas, key=lambda d: abs(d["delta_pp"]), reverse=True)[:3]
    base_dec: dict[str, int] = s._DRIFT_BASELINE.get("decisions", {}) or {}
    cur_dec: dict[str, int] = snap.get("decisions", {}) or {}
    decision_deltas: list[dict[str, Any]] = []
    for d in sorted(set(base_dec) | set(cur_dec)):
        base_pct = (base_dec.get(d, 0) / base_total) * 100
        cur_pct = (cur_dec.get(d, 0) / cur_total * 100) if cur_total else 0.0
        decision_deltas.append(
            {
                "decision": d,
                "baseline_pct": round(base_pct, 2),
                "current_pct": round(cur_pct, 2),
                "delta_pp": round(cur_pct - base_pct, 2),
            }
        )
    return {
        "baseline_captured": True,
        "baseline_captured_at": s._DRIFT_BASELINE["captured_at"],
        "baseline_source": s._DRIFT_BASELINE.get("source", "auto"),
        "baseline_queries": base_total,
        "current_queries": cur_total,
        "tv_distance": tv_distance,
        "drift_severity": (
            "high" if tv_distance > 0.20
            else "moderate" if tv_distance > 0.10
            else "low"
        ),
        "intent_deltas": deltas,
        "top_movers": movers,
        "decision_deltas": decision_deltas,
        "auto_rebaseline_every": s._DRIFT_AUTO_REBASELINE_EVERY,
        "queries_until_next_auto_rebaseline": (
            max(
                0,
                s._DRIFT_AUTO_REBASELINE_EVERY
                - (s._METRICS.queries_total - s._DRIFT_LAST_AUTO_REBASELINE_AT_QUERY),
            )
            if s._DRIFT_AUTO_REBASELINE_EVERY > 0
            else None
        ),
    }


@router.post("/drift/baseline")
def drift_baseline_capture(
    operator: str = "",
    principal: dict[str, Any] | None = Depends(verify_token),
) -> dict[str, Any]:
    """Manually capture the current distribution as the new drift baseline.

    Bridge hub connection: lets an operator rebaseline after a known
    upstream change (new marketing campaign, release of a new product)
    so the dashboard's drift signal reflects deviation from the new
    normal rather than the historical first-50.
    """
    operator = principal["sub"] if principal else operator
    s = _server()
    new_baseline = s._snapshot_for_baseline("manual")
    # Replace globals via setattr so other readers (the GET above, the
    # background rebaseliner) see the new values.
    s._DRIFT_BASELINE = new_baseline
    s._DRIFT_LAST_AUTO_REBASELINE_AT_QUERY = s._METRICS.queries_total
    _audit_drift_event(
        s, "drift.rebaseline", operator,
        baseline_queries=new_baseline["queries_total"], source="manual",
    )
    return {
        "status": "captured",
        "captured_at": new_baseline["captured_at"],
        "baseline_queries": new_baseline["queries_total"],
        "intents_in_baseline": sorted(new_baseline["queries_by_intent"].keys()),
    }


@router.post("/drift/auto-rebaseline")
def drift_auto_rebaseline_set(
    every: int,
    operator: str = "",
    principal: dict[str, Any] | None = Depends(verify_token),
) -> dict[str, Any]:
    """Enable/disable periodic auto-rebaseline at runtime.

    Bridge hub connection: ops can toggle the rolling baseline cadence
    without restarting the backend. ``every=0`` disables; ``every=N>0``
    rebaselines every N queries.
    """
    operator = principal["sub"] if principal else operator
    if every < 0 or every > 100_000:
        raise HTTPException(
            status_code=422,
            detail=f"every={every} out of range [0, 100000]",
        )
    s = _server()
    before = s._DRIFT_AUTO_REBASELINE_EVERY
    s._DRIFT_AUTO_REBASELINE_EVERY = every
    if every != before:
        _audit_drift_event(s, "drift.auto_rebaseline", operator, before=before, after=every)
    return {
        "status": "ok",
        "auto_rebaseline_every": every,
        "queries_until_next": every if every > 0 else None,
    }


__all__ = ["router"]
