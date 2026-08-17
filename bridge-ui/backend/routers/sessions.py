# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Sessions — the audit trail grouped by client/conversation (product #2).

The raw audit is a flat stream of events (#348, #347, …). A bank operator wants
to see a *conversation*: pick a client and inspect the whole flow — every query,
intent, decision, cost and PII event for that session, end to end. This endpoint
groups the in-memory audit (`_AUDIT`) by ``customer_id`` and returns per-session
aggregates plus the ordered event list, so the UI can show "operate like a bank"
instead of loose log lines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

if TYPE_CHECKING:
    from types import ModuleType

router = APIRouter()


def _server() -> ModuleType:
    import sys

    mod = sys.modules.get("server") or sys.modules.get("backend.server")
    if mod is not None:
        return mod
    try:
        import server  # type: ignore[no-redef]
    except ImportError:
        from backend import server
    return server


def build_sessions() -> dict[str, Any]:
    """Group the in-memory audit trail by client into conversation sessions."""
    s = _server()
    # Only CUSTOMER decisions belong in a by-customer view. Operational events
    # (governance.*, settings.change, drift.*) carry an "event" key and no customer_id —
    # including them invented a phantom "—" customer whose decision histogram mixed
    # PENDING/APPROVED/APPLIED in with real guard verdicts.
    try:
        from routers.audit import _is_operational_entry
    except ImportError:
        from backend.routers.audit import _is_operational_entry  # type: ignore[no-redef]
    # Only customer decisions belong in a by-customer view; operational/synthetic entries do
    # not. The predicate also catches rehydrated rows written before the "event" key existed.
    entries = [e for e in list(s._AUDIT) if not _is_operational_entry(e)]
    groups: dict[str, dict[str, Any]] = {}
    for e in entries:
        cid = e.get("customer_id") or "—"
        g = groups.setdefault(
            cid,
            {
                "customer_id": cid,
                "channels": set(),
                "events": [],
                "decisions": {},
                "pii_events": 0,
                "cost_cents": 0.0,
            },
        )
        g["channels"].add(e.get("channel") or "—")
        decision = e.get("decision", "?")
        g["decisions"][decision] = g["decisions"].get(decision, 0) + 1
        if e.get("pii_count"):
            g["pii_events"] += 1
        g["cost_cents"] += e.get("cost_cents") or 0.0
        g["events"].append(
            {
                "seq": e.get("seq"),
                "ts": e.get("ts"),
                "query": e.get("query"),  # already PII-masked by the audit append
                "intent": e.get("intent"),
                "confidence": e.get("confidence"),
                "decision": decision,
                "cost_cents": e.get("cost_cents"),
                "pii_count": e.get("pii_count", 0),
                "from_cache": e.get("from_cache", False),
            }
        )

    sessions: list[dict[str, Any]] = []
    for g in groups.values():
        evs = g["events"]
        sessions.append(
            {
                "customer_id": g["customer_id"],
                "channels": sorted(g["channels"]),
                "n_events": len(evs),
                "decisions": g["decisions"],
                "pii_events": g["pii_events"],
                "cost_cents": round(g["cost_cents"], 2),
                "first_ts": evs[0]["ts"] if evs else None,
                "last_ts": evs[-1]["ts"] if evs else None,
                "events": evs,
            }
        )
    sessions.sort(key=lambda x: x["last_ts"] or 0, reverse=True)
    return {"n_sessions": len(sessions), "n_events": len(entries), "sessions": sessions}


@router.get("/sessions")
def sessions_endpoint() -> dict[str, Any]:
    """Return the audit trail grouped by client into conversation sessions."""
    return build_sessions()


__all__ = ["router"]
