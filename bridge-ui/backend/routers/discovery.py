# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Discovery / catalog endpoints.

Six read-only endpoints that expose **what the platform knows about
itself** to a dashboard or auditor: which agents exist, which intents the
classifier can emit, which customers have persistent memory, what the
RAG corpus contains, and the cumulative DQ/DG hit counters.

State (``_METRICS``, ``_CUSTOMER_MEMORY``, ``_DOC_STORE``, ``_AUDIT``,
``_DQ_INPUT/_DQ_OUTPUT``, ``_DQ_DG_STATS``) plus the static
``_INTENT_CATALOG`` live in ``server.py`` and are fetched lazily via
:func:`_server` to break the ``server -> routers`` circular import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException

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


@router.get("/agents")
def agents() -> dict[str, Any]:
    """List the Bridge agents and the intents each one currently handles.

    Bridge hub connection: static registry view of the agents the Bridge
    router can dispatch to — chatbot, smart_payments, call_center — used
    by the dashboard to show fleet status.
    """
    return {
        "agents": [
            {
                "name": "chatbot",
                "status": "active",
                "intents": ["balance", "loan", "card", "complaint", "general"],
            },
            {"name": "smart_payments", "status": "active", "intents": ["transfer", "pix"]},
            {"name": "call_center", "status": "standby", "intents": []},
        ]
    }


@router.get("/intents")
def intents() -> dict[str, Any]:
    """Return the full intent catalog plus live per-intent firing counts.

    Bridge hub connection: gives the dashboard / auditor a single
    source-of-truth view of which intent labels the classifier can emit,
    which agent handles each, and what guard verdict it forces — joined
    with live counts from the in-memory Metrics so reviewers can see
    actual coverage during a demo without grepping source.
    """
    s = _server()
    snap = s._METRICS.snapshot()
    by_intent: dict[str, int] = snap.get("queries_by_intent", {}) or {}
    total = snap.get("queries_total", 0) or 0
    enriched: list[dict[str, Any]] = []
    family_totals: dict[str, int] = {}
    for entry in s._INTENT_CATALOG:
        count = int(by_intent.get(entry["name"], 0))
        pct = round((count / total) * 100, 1) if total else 0.0
        enriched.append({**entry, "count": count, "percent": pct})
        family_totals[entry["family"]] = family_totals.get(entry["family"], 0) + count
    # Theme A: merge applied governed intent policies so the catalog reflects what the
    # runtime now honours — a new governed intent appears as a row; an existing one is
    # marked governed and shows its overridden decision.
    static_names = {e["name"] for e in s._INTENT_CATALOG}
    try:
        governed = s._governed_intent_policies()
    except Exception:  # noqa: BLE001 — overlay is best-effort
        governed = {}
    for gname, gcfg in governed.items():
        if gname in static_names:
            for e in enriched:
                if e["name"] == gname:
                    e["governed"] = True
                    if gcfg.get("default_decision"):
                        e["default_decision"] = gcfg["default_decision"]
                    break
            continue
        gfam = str(gcfg.get("family") or "banking")
        gcount = int(by_intent.get(gname, 0))
        enriched.append({
            "name": gname,
            "family": gfam,
            "agent": str(gcfg.get("agent") or "chatbot"),
            "default_decision": str(gcfg.get("default_decision") or "by-confidence"),
            "description": str(gcfg.get("description") or "Governed intent (approved + applied)."),
            "samples": list(gcfg.get("samples") or []),
            "count": gcount,
            "percent": round((gcount / total) * 100, 1) if total else 0.0,
            "governed": True,
        })
        family_totals[gfam] = family_totals.get(gfam, 0) + gcount
    return {
        "intents": enriched,
        "families": family_totals,
        "total_queries": total,
        "catalog_size": len(enriched),
    }


@router.get("/customers")
def customers() -> dict[str, Any]:
    """List customers with persistent memory + their block names."""
    s = _server()
    out = []
    for cid in s._CUSTOMER_MEMORY.list_customers():
        snap = s._CUSTOMER_MEMORY.snapshot(cid)
        out.append(
            {
                "customer_id": cid,
                "blocks": list(snap.keys()),
                "block_summaries": {n: b.content[:80] for n, b in snap.items()},
            }
        )
    return {"customers": out, "total": len(out)}


@router.get("/customers/{customer_id}")
def customer_detail(customer_id: str) -> dict[str, Any]:
    """Return all persistent memory blocks for a single customer.

    Bridge hub connection: exposes the Letta/MemGPT-style CustomerMemory
    that Stage 3 of the Bridge pipeline reads when personalizing replies,
    plus the exact rendered prompt context that would be injected.
    """
    s = _server()
    snap = s._CUSTOMER_MEMORY.snapshot(customer_id)
    if not snap:
        raise HTTPException(
            status_code=404,
            detail=(
                f"customer_id={customer_id!r} has no memory blocks. "
                "Memory is read-only in this demo (see DEMO_SCOPE.md §4) — "
                "send a query for that customer first to seed blocks."
            ),
        )
    return {
        "customer_id": customer_id,
        "blocks": {
            n: {
                "content": b.content,
                "updated_at": b.updated_at,
                "update_count": b.update_count,
            }
            for n, b in snap.items()
        },
        "rendered": s._CUSTOMER_MEMORY.render_prompt_context(customer_id),
    }


@router.get("/docs/corpus")
def docs_corpus() -> dict[str, Any]:
    """List the RAG corpus that Stage 4 of the Bridge pipeline retrieves from."""
    s = _server()
    return {
        "documents": [
            {"id": d.id, "source": d.source, "text_preview": d.text[:120]}
            for d in s._DOC_STORE.all()
        ],
        "total": s._DOC_STORE.size,
    }


@router.get("/dq-dg")
def dq_dg_stats() -> dict[str, Any]:
    """Aggregated Data Quality + Data Governance counters.

    Separates two axes so the panel never reads zero after an audit rotation:
      - ``since_startup_*`` : monotonic counters from process start
      - ``current_window_*``: derived from the current /audit window

    The legacy flat fields are preserved for back-compat.
    """
    s = _server()
    total_queries = s._METRICS.queries_total or 1
    pii_rate = s._DQ_DG_STATS["queries_with_pii"] / total_queries

    # Snapshot the shared deque once — iterating _AUDIT live races a
    # concurrent /query append (RuntimeError 500), same class as the /audit fix.
    # The trail also carries OPERATIONAL events (governance.submit/.decision/.apply,
    # settings.change, drift.*) — they all set "event"; a customer query never does.
    # Counting them as queries would inflate the DQ window (a config approval is not a
    # customer request) and dilute the PII rate.
    try:
        from routers.audit import _is_operational_entry
    except ImportError:
        from backend.routers.audit import _is_operational_entry  # type: ignore[no-redef]
    # Operational entries (governance/settings/drift/rotation/probe) are not customer queries.
    # The predicate also recognises rehydrated rows that predate the "event" key.
    audit_snapshot = [e for e in list(s._AUDIT) if not _is_operational_entry(e)]
    window_queries = len(audit_snapshot)
    window_with_pii = sum(1 for e in audit_snapshot if e.get("query_was_masked"))
    window_pii_masked = sum(int(e.get("pii_count", 0)) for e in audit_snapshot)

    return {
        **s._DQ_DG_STATS,
        "total_queries": s._METRICS.queries_total,
        "pii_detection_rate": round(pii_rate, 3),
        "input_rules_active": len(s._DQ_INPUT.rules),
        "output_rules_active": len(s._DQ_OUTPUT.rules),
        # since_startup_* — same numbers, clearer name.
        "since_startup_queries": s._METRICS.queries_total,
        "since_startup_input_blocks": s._DQ_DG_STATS["input_blocks"],
        "since_startup_output_blocks": s._DQ_DG_STATS["output_blocks"],
        "since_startup_queries_with_pii": s._DQ_DG_STATS["queries_with_pii"],
        "since_startup_pii_masked_total": s._DQ_DG_STATS["pii_masked_total"],
        # current_window_* derived from retained audit entries only.
        "current_window_queries": window_queries,
        "current_window_queries_with_pii": window_with_pii,
        "current_window_pii_masked_total": window_pii_masked,
    }


__all__ = ["router"]
