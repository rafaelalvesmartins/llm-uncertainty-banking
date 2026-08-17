# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""lub.dashboard.in_memory_source -- bridge an in-memory ledger to a SnapshotSource.

Pass-39 (per spec 31 follow-on): connects two previously unrelated
plug-points:

* :class:`~lub.ledger.protocol.InMemoryLedger` (pass 38) -- a fast
  test-double LedgerProtocol implementation, no sqlite needed.
* :class:`~lub.dashboard.protocols.SnapshotSource` (pass 33) -- the
  dashboard's data-side Protocol.

Bridge: :class:`InMemorySnapshotSource` walks the in-memory ledger's
internal lists to compute the four KPIs the dashboard expects. Means
the entire dashboard rendering stack can be unit-tested in <1 ms without
touching sqlite, FastAPI, or the filesystem.

Usage::

    from lub.dashboard import build_snapshot, render_html
    from lub.dashboard.in_memory_source import InMemorySnapshotSource
    from lub.ledger.protocol import InMemoryLedger

    led = InMemoryLedger()
    qid = led.log_query("Q?", domain="banking")
    aid = led.log_answer(qid, "gpt-4o", "openai", "yes", tier="prime")
    led.log_policy(aid, "EMIT", 0.7, True, "ok")

    snap = build_snapshot(
        InMemorySnapshotSource(led),
        period_start=..., period_end=...,
    )
    html = render_html(snap)

Spec: planning/31_Storage_Genericity_Spec_2026-04-25.md (follow-on).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

__all__ = ["InMemorySnapshotSource"]


class InMemorySnapshotSource:
    """Bridge an InMemoryLedger (or any compatible in-memory ledger) into
    a :class:`~lub.dashboard.protocols.SnapshotSource`.

    Accepts any object with the InMemoryLedger internal-list shape:
    ``_queries``, ``_answers``, ``_scores``, ``_policies``, ``_outcomes``.
    The bridge does not require sqlite, so the entire dashboard stack
    becomes unit-testable in pure-Python with no filesystem touch.

    Args:
        ledger: An :class:`~lub.ledger.protocol.InMemoryLedger` instance
            (or any object exposing the same internal lists).
        date_filter: Optional callable ``(row) -> bool`` to filter
            decisions by domain or other attributes. Default: pass-through.
    """

    def __init__(self, ledger: Any) -> None:
        for attr in ("_queries", "_answers", "_policies", "_outcomes"):
            if not hasattr(ledger, attr):
                raise TypeError(f"ledger must expose .{attr}; got {type(ledger).__name__}")
        self._ledger = ledger

    # -- SnapshotSource Protocol implementation ---------------------------

    def kpi_decisions(self, start: datetime, end: datetime) -> tuple[int, float]:
        """Count all policy decisions and the abstention rate.

        The in-memory ledger does not track per-row timestamps, so the
        ``start`` / ``end`` window is ignored — every decision is
        considered in-window. Plug-ins that want true window filtering
        should subclass and override.
        """
        policies = self._ledger._policies
        n = len(policies)
        if n == 0:
            return 0, 0.0
        abstained = sum(1 for p in policies if not p.get("passed"))
        return n, abstained / n

    def kpi_outcomes(
        self,
        start: datetime,
        end: datetime,
    ) -> tuple[int, float | None]:
        """Count labelled outcomes and the empirical correctness rate.

        Returns ``(0, None)`` when no outcomes have been logged so
        the dashboard can render "no data" instead of a misleading 0%.
        """
        outcomes = self._ledger._outcomes
        n = len(outcomes)
        if n == 0:
            return 0, None
        n_correct = sum(1 for o in outcomes.values() if o.get("correct"))
        return n, n_correct / n

    def kpi_meta_calibration_ece(self) -> float | None:
        """Always ``None`` — in-memory ledger has no CEC meta-cal table.

        The CEC (Calibrated Evidence Chain) tables are sqlite-only;
        plug-ins that mirror them in-memory should subclass and
        override this method.
        """
        return None

    def recent_decisions(
        self,
        start: datetime,
        end: datetime,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` most recent decisions in reverse insertion order.

        The in-memory ledger does not store per-row timestamps, so the
        ``start`` / ``end`` window is ignored — every recorded policy
        decision is considered in-window. Performs an in-memory join
        across ``_policies``, ``_answers``, and ``_queries`` to produce
        the same row shape the sqlite-backed source emits (``id``,
        ``decision``, ``threshold``, ``passed``, ``reason``,
        ``created_at``, ``model``, ``tier``, ``domain``); ``created_at``
        is the literal string ``"in-memory"`` since no timestamps exist.
        """
        # Cross-table join: policies + answers + queries.
        ans_by_id = {a["id"]: a for a in self._ledger._answers}
        q_by_id = {q["id"]: q for q in self._ledger._queries}
        out: list[dict[str, Any]] = []
        if limit <= 0:
            return out
        # Iterate policies in reverse insertion order (most recent first).
        for p in reversed(self._ledger._policies):
            a = ans_by_id.get(p["answer_id"])
            q = q_by_id.get(a["query_id"]) if a else None
            out.append(
                {
                    "id": p.get("id"),
                    "decision": p.get("decision"),
                    "threshold": p.get("threshold"),
                    "passed": p.get("passed"),
                    "reason": p.get("reason"),
                    "created_at": "in-memory",
                    "model": (a or {}).get("model"),
                    "tier": (a or {}).get("tier"),
                    "domain": (q or {}).get("domain"),
                }
            )
            if len(out) >= limit:
                break
        return out
