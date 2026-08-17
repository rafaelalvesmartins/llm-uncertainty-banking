# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""lub.dashboard.ledger_source -- SnapshotSource backed by an LUB ledger.

This is the **default** :class:`~lub.dashboard.protocols.SnapshotSource`
implementation. All sqlite-specific code that used to live in
``lub.dashboard.query`` (KPI SQL queries, schema-coupled column names)
lives here so the rest of the dashboard subpackage stays generic.

Other implementations live alongside this one but are intentionally not
core dependencies:

* CSV-backed (for offline ad-hoc reports)
* Prometheus-backed (for live metrics)
* Composite (fan-out across many sources, e.g. multi-tenant dashboards)

All of them satisfy :class:`~lub.dashboard.protocols.SnapshotSource`
structurally; none is required.

Spec: planning/29_Dashboard_Spec_2026-04-25.md (post pass-33 refactor).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

__all__ = ["LedgerSnapshotSource", "iso_timestamp"]


def iso_timestamp(dt: datetime) -> str:
    """Format a datetime as ledger-compatible ISO 8601 with 'Z' suffix.

    Ledger ``created_at`` columns are stored as
    ``strftime('%Y-%m-%dT%H:%M:%fZ', 'now')``, so direct string comparison
    works against the same shape.
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class LedgerSnapshotSource:
    """SnapshotSource that reads from an LUB ledger sqlite handle.

    Wraps a :class:`~lub.ledger.Ledger` (or any object exposing a sqlite3
    ``_conn`` attribute with the standard schema). All four KPI methods
    are implemented over that connection; meta-cal ECE is computed from
    the ``cec_meta_*`` schema-v2 tables when present.

    Constructor accepts the ledger directly so the dashboard subpackage
    does not import :mod:`lub.ledger` itself -- the dependency direction
    is "consumer constructs the source and passes it in", not "dashboard
    pulls the ledger module in".
    """

    def __init__(self, ledger: Any) -> None:
        conn = getattr(ledger, "_conn", None)
        if conn is None:
            raise TypeError(
                f"ledger must expose a sqlite3 ._conn attribute (got {type(ledger).__name__})"
            )
        self._conn = conn
        self._ledger = ledger  # keep reference so caller can't gc it under us

    # -- SnapshotSource Protocol implementation ---------------------------

    def kpi_decisions(self, start: datetime, end: datetime) -> tuple[int, float]:
        """Count policy decisions in window and the share that abstained.

        Returns ``(n_decisions, abstention_rate)`` where the rate is
        ``0.0`` when the window is empty (rather than NaN).
        """
        row = self._conn.execute(
            "SELECT COUNT(*) AS n,"
            "       COALESCE(SUM(CASE WHEN passed = 0 THEN 1 ELSE 0 END), 0) AS abstained"
            " FROM policy_decisions"
            " WHERE created_at BETWEEN ? AND ?",
            (iso_timestamp(start), iso_timestamp(end)),
        ).fetchone()
        n = int(row["n"]) if row else 0
        abstained = int(row["abstained"]) if row else 0
        rate = (abstained / n) if n > 0 else 0.0
        return n, rate

    def kpi_outcomes(
        self,
        start: datetime,
        end: datetime,
    ) -> tuple[int, float | None]:
        """Count labelled outcomes in window and the empirical correctness rate.

        Returns ``(n_outcomes, correctness_rate)`` where the rate is
        ``None`` (not 0.0) when the window has no labelled outcomes —
        so the dashboard can render "no data" instead of "0% correct".
        """
        row = self._conn.execute(
            "SELECT COUNT(*) AS n,"
            "       COALESCE(SUM(correct), 0) AS n_correct"
            " FROM outcomes"
            " WHERE labelled_at BETWEEN ? AND ?",
            (iso_timestamp(start), iso_timestamp(end)),
        ).fetchone()
        n = int(row["n"]) if row else 0
        correct = int(row["n_correct"]) if row else 0
        rate = (correct / n) if n > 0 else None
        return n, rate

    def kpi_meta_calibration_ece(self, n_buckets: int = 10) -> float | None:
        """Equal-width binned ECE over the meta-calibration claim log.

        Joins ``cec_meta_predictions`` with ``cec_meta_outcomes`` and
        computes Expected Calibration Error across ``n_buckets``
        equal-width bins on ``[0, 1]``. Returns ``None`` if no claims
        have been recorded yet.
        """
        rows = self._conn.execute(
            "SELECT p.predicted_confidence AS conf, o.held_up AS held_up"
            " FROM cec_meta_predictions p"
            " JOIN cec_meta_outcomes o ON o.claim_id = p.claim_id"
        ).fetchall()
        if not rows:
            return None
        width = 1.0 / n_buckets
        buckets: list[list[tuple[float, int]]] = [[] for _ in range(n_buckets)]
        for r in rows:
            conf = float(r["conf"])
            conf = min(max(conf, 0.0), 1.0)
            idx = min(int(conf / width), n_buckets - 1)
            buckets[idx].append((conf, int(r["held_up"])))
        n_total = sum(len(b) for b in buckets)
        if n_total == 0:
            return None
        ece = 0.0
        for b in buckets:
            if not b:
                continue
            mean_conf = sum(c for c, _ in b) / len(b)
            accuracy = sum(h for _, h in b) / len(b)
            ece += (len(b) / n_total) * abs(mean_conf - accuracy)
        return ece

    def recent_decisions(
        self,
        start: datetime,
        end: datetime,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` recent decisions in window, newest first.

        Runs a single SQL join across ``policy_decisions``, ``answers``,
        and ``queries`` filtered by ``policy_decisions.created_at``
        between ``start`` and ``end`` (formatted via
        :func:`iso_timestamp`). Returns each row as a dict with keys
        ``id``, ``decision``, ``threshold``, ``passed``, ``reason``,
        ``created_at``, ``model``, ``tier``, ``domain`` — matching the
        :class:`~lub.dashboard.protocols.SnapshotSource` Protocol shape.
        """
        rows = self._conn.execute(
            "SELECT pd.id, pd.decision, pd.threshold, pd.passed, pd.reason,"
            "       pd.created_at, a.model, a.tier, q.domain"
            " FROM policy_decisions pd"
            " JOIN answers a ON a.id = pd.answer_id"
            " JOIN queries q ON q.id = a.query_id"
            " WHERE pd.created_at BETWEEN ? AND ?"
            " ORDER BY pd.created_at DESC"
            " LIMIT ?",
            (iso_timestamp(start), iso_timestamp(end), int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]
