# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""lub.ledger.protocol -- pluggable durable-audit-log surface.

Pass-38 (per spec 31 section 2.2): introduces :class:`LedgerProtocol` so
plug-in audit-log backends (Postgres, DuckDB, Parquet-on-S3, an
in-memory test double, etc.) can drop in without modifying
:mod:`lub.ledger.store` or its many consumers (`lub.challenge.*`,
`lub.dashboard.LedgerSnapshotSource`, `lub.orchestration.swarm`).

The existing :class:`~lub.ledger.store.Ledger` (sqlite-backed) already
satisfies this Protocol structurally for its public-method surface. A
simple :class:`InMemoryLedger` ships alongside as the canonical
"how do I write a ledger plug-in" reference and a fast test double for
unit tests of `lub.dashboard` / `lub.challenge`.

This module is **purely additive** -- nothing in the existing ledger
module changes. v0.1 callers continue to construct
:class:`Ledger` directly; v0.3+ callers can use any object satisfying
:class:`LedgerProtocol`.

The Protocol now also includes :meth:`LedgerProtocol.summary` so
first-party metric exporters (:mod:`lub.ledger.metrics`) no longer
need to reach into the sqlite-specific ``_conn`` attribute. Backends
that cannot compute aggregates efficiently are free to implement
``summary`` by iterating their internal storage (see
:class:`InMemoryLedger`).

Spec: planning/31_Storage_Genericity_Spec_2026-04-25.md section 2.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "LedgerProtocol",
    "LedgerSummary",
    "InMemoryLedger",
]


@dataclass(frozen=True)
class LedgerSummary:
    """Aggregate counts derived from a :class:`LedgerProtocol` snapshot.

    All fields are concrete numbers / mappings -- no SQL, no cursors --
    so :mod:`lub.ledger.metrics` can compute Prometheus / Grafana
    payloads from any :class:`LedgerProtocol` implementation, not just
    the sqlite-backed :class:`~lub.ledger.store.Ledger`.

    Attributes
    ----------
    n_answers:
        Count of rows in the ``answers`` log.
    n_scored:
        Count of rows in the ``uq_scores`` log.
    n_outcomes:
        Count of rows in the ``outcomes`` log.
    n_correct:
        Count of ``outcomes`` rows whose ``correct`` flag is true.
    n_policy_decisions:
        Count of rows in the ``policy_decisions`` log.
    n_abstain:
        Count of ``policy_decisions`` rows whose ``decision`` equals
        ``"abstain"``.
    tier_counts:
        Mapping ``label -> count`` where ``label`` is each answer's
        ``tier`` field if non-null, falling back to ``model``.
    distinct_methods:
        Sorted list of distinct ``method`` values seen in
        ``uq_scores`` -- i.e. every UQ method that has ever been
        logged against this ledger.
    """

    n_answers: int
    n_scored: int
    n_outcomes: int
    n_correct: int
    n_policy_decisions: int
    n_abstain: int
    tier_counts: dict[str, int] = field(default_factory=dict)
    distinct_methods: list[str] = field(default_factory=list)


@runtime_checkable
class LedgerProtocol(Protocol):
    """Abstract durable audit log of {query, answer, score, policy, outcome}.

    The minimum surface mirrors the public methods of
    :class:`~lub.ledger.store.Ledger`. Storage-specific attributes
    (e.g. ``_conn``) are intentionally NOT part of the Protocol --
    use :meth:`summary` for aggregates that previously required
    direct cursor access.
    """

    def log_query(self, prompt: str, domain: str = "generic") -> int:
        """Append a query row and return its new id."""
        ...

    def log_answer(
        self,
        query_id: int,
        model: str,
        backend: str,
        answer: str,
        *,
        tier: str | None = None,
        latency_ms: float | None = None,
        cost: float = 0.0,
    ) -> int:
        """Append an answer row tied to ``query_id`` and return its new id."""
        ...

    def log_score(self, answer_id: int, method: str, value: float) -> int:
        """Append a UQ score row for ``answer_id`` and return its new id."""
        ...

    def log_policy(
        self,
        answer_id: int,
        decision: str,
        threshold: float,
        passed: bool,
        reason: str = "",
    ) -> int:
        """Append a policy-decision row for ``answer_id`` and return its new id."""
        ...

    def update_outcome(
        self,
        answer_id: int,
        *,
        correct: bool,
        ground_truth: str | None = None,
        human_verdict: str | None = None,
    ) -> None:
        """Upsert the outcome (correctness + optional ground truth) for ``answer_id``."""
        ...

    def fetch_answer(self, answer_id: int) -> dict[str, Any] | None:
        """Return the answer row as a dict, or ``None`` if not found."""
        ...

    def fetch_scores(self, answer_id: int) -> list[dict[str, Any]]:
        """Return all ``{method, value}`` score rows for ``answer_id``."""
        ...

    def summary(self) -> LedgerSummary:
        """Return aggregate counts across the ledger as a :class:`LedgerSummary`."""
        ...

    def close(self) -> None:
        """Release any underlying resources (connections, file handles)."""
        ...


class InMemoryLedger:
    """Tiny in-memory ledger -- canonical plug-in reference.

    All log calls append to per-table lists; all fetch calls scan those
    lists. Use for fast unit tests; the real
    :class:`~lub.ledger.store.Ledger` (sqlite) is canonical for anything
    persistent.
    """

    def __init__(self) -> None:
        self._queries: list[dict[str, Any]] = []
        self._answers: list[dict[str, Any]] = []
        self._scores: list[dict[str, Any]] = []
        self._policies: list[dict[str, Any]] = []
        self._outcomes: dict[int, dict[str, Any]] = {}
        self._next_id = 1

    def _new_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    # -- LedgerProtocol implementation ------------------------------------

    def log_query(self, prompt: str, domain: str = "generic") -> int:
        """Append a query row and return its new id."""
        qid = self._new_id()
        self._queries.append({"id": qid, "prompt": prompt, "domain": domain})
        return qid

    def log_answer(
        self,
        query_id: int,
        model: str,
        backend: str,
        answer: str,
        *,
        tier: str | None = None,
        latency_ms: float | None = None,
        cost: float = 0.0,
    ) -> int:
        """Append an answer row tied to ``query_id`` and return its new id."""
        aid = self._new_id()
        self._answers.append(
            {
                "id": aid,
                "query_id": query_id,
                "model": model,
                "backend": backend,
                "answer": answer,
                "tier": tier,
                "latency_ms": latency_ms,
                "cost": cost,
            }
        )
        return aid

    def log_score(self, answer_id: int, method: str, value: float) -> int:
        """Append a UQ score row for ``answer_id`` and return its new id."""
        sid = self._new_id()
        self._scores.append(
            {
                "id": sid,
                "answer_id": answer_id,
                "method": method,
                "value": float(value),
            }
        )
        return sid

    def log_policy(
        self,
        answer_id: int,
        decision: str,
        threshold: float,
        passed: bool,
        reason: str = "",
    ) -> int:
        """Append a policy-decision row for ``answer_id`` and return its new id."""
        pid = self._new_id()
        self._policies.append(
            {
                "id": pid,
                "answer_id": answer_id,
                "decision": decision,
                "threshold": float(threshold),
                "passed": int(bool(passed)),
                "reason": reason,
            }
        )
        return pid

    def update_outcome(
        self,
        answer_id: int,
        *,
        correct: bool,
        ground_truth: str | None = None,
        human_verdict: str | None = None,
    ) -> None:
        """Upsert the outcome (correctness + optional ground truth) for ``answer_id``."""
        self._outcomes[answer_id] = {
            "answer_id": answer_id,
            "correct": int(bool(correct)),
            "ground_truth": ground_truth,
            "human_verdict": human_verdict,
        }

    def fetch_answer(self, answer_id: int) -> dict[str, Any] | None:
        """Return the answer row as a dict, or ``None`` if not found."""
        for a in self._answers:
            if a["id"] == answer_id:
                return dict(a)
        return None

    def fetch_scores(self, answer_id: int) -> list[dict[str, Any]]:
        """Return all ``{method, value}`` score rows for ``answer_id``."""
        return [
            {"method": s["method"], "value": s["value"]}
            for s in self._scores
            if s["answer_id"] == answer_id
        ]

    def summary(self) -> LedgerSummary:
        """Compute aggregate counts across the in-memory tables."""
        n_correct = sum(1 for o in self._outcomes.values() if o.get("correct"))
        n_abstain = sum(1 for p in self._policies if p.get("decision") == "abstain")
        tier_counts: dict[str, int] = {}
        for a in self._answers:
            label = a.get("tier") or a.get("model") or ""
            tier_counts[str(label)] = tier_counts.get(str(label), 0) + 1
        distinct_methods = sorted({str(s["method"]) for s in self._scores})
        return LedgerSummary(
            n_answers=len(self._answers),
            n_scored=len(self._scores),
            n_outcomes=len(self._outcomes),
            n_correct=n_correct,
            n_policy_decisions=len(self._policies),
            n_abstain=n_abstain,
            tier_counts=tier_counts,
            distinct_methods=distinct_methods,
        )

    def close(self) -> None:
        """No-op; in-memory ledger has no resources to release."""
        # In-memory ledger -- nothing to release.
        return
