# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""High-level interface to the uncertainty ledger."""

from __future__ import annotations

import functools
import hashlib
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import structlog

from lub.ledger.protocol import LedgerSummary
from lub.ledger.schema import SCHEMA_SQL, SCHEMA_VERSION

_LOG = structlog.get_logger("lub.ledger.store")

_T = TypeVar("_T")

# Tunables for transient-error retry. Kept as module-level constants
# (not config / env vars) because the values are conservative and
# tightly coupled to sqlite's lock-resolution behaviour: a few short
# retries with exponential backoff cover virtually all real-world
# contention without making latency under heavy load worse.
_RETRY_MAX_ATTEMPTS = 4
_RETRY_BASE_DELAY_S = 0.02


def _is_transient_sqlite_error(exc: BaseException) -> bool:
    """True for sqlite errors that resolve on retry (lock / busy)."""
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    msg = str(exc).lower()
    return "lock" in msg or "busy" in msg


def _retry_on_transient(
    fn: Callable[..., _T],
) -> Callable[..., _T]:
    """Retry decorator for Ledger write methods.

    Wraps a method so transient ``sqlite3.OperationalError`` failures
    ("database is locked" / "database is busy") are retried with
    exponential backoff. Non-transient errors propagate immediately.

    The wrapped method is expected to be idempotent across the retry
    boundary -- which all our writes are, because they create their
    own transaction via :meth:`Ledger._tx` and that transaction is
    rolled back when the inner operation raises before the commit.
    """

    @functools.wraps(fn)
    def wrapper(self: Ledger, *args: Any, **kwargs: Any) -> _T:
        """Invoke the wrapped method, retrying on transient sqlite errors."""
        last_exc: BaseException | None = None
        for attempt in range(_RETRY_MAX_ATTEMPTS):
            try:
                return fn(self, *args, **kwargs)
            except Exception as exc:
                if not _is_transient_sqlite_error(exc):
                    raise
                last_exc = exc
                if attempt == _RETRY_MAX_ATTEMPTS - 1:
                    _LOG.warning(
                        "ledger.write.retry_exhausted",
                        method=fn.__name__,
                        attempts=_RETRY_MAX_ATTEMPTS,
                        error=str(exc),
                    )
                    raise
                delay = _RETRY_BASE_DELAY_S * (2**attempt)
                _LOG.debug(
                    "ledger.write.retry",
                    method=fn.__name__,
                    attempt=attempt + 1,
                    delay_s=delay,
                    error=str(exc),
                )
                time.sleep(delay)
        # Mypy needs an explicit raise here; the loop above always
        # either returns or re-raises, so this is unreachable.
        assert last_exc is not None  # pragma: no cover
        raise last_exc

    return wrapper


@dataclass(frozen=True)
class CalibrationPoint:
    """One row of a reliability diagram derived from the ledger.

    Attributes
    ----------
    bucket:
        Index of the confidence bin, starting at 0.
    bucket_low:
        Inclusive lower bound of the confidence bin.
    bucket_high:
        Exclusive upper bound (inclusive for the last bin).
    confidence_mean:
        Mean confidence of answers whose UQ score fell in this bin.
    accuracy:
        Empirical correctness rate among answers in this bin.
    n:
        Number of answers in this bin.
    """

    bucket: int
    bucket_low: float
    bucket_high: float
    confidence_mean: float
    accuracy: float
    n: int


class Ledger:
    """Durable, queryable audit log for the runtime.

    Parameters
    ----------
    path:
        SQLite file. ``":memory:"`` is accepted and handy in tests.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        # The SCHEMA_SQL migrations are additive (CREATE TABLE IF NOT EXISTS),
        # so the executescript above upgrades an older file in place -- stamp
        # the version the file now has, not the one it was born with.
        self._conn.execute(
            "INSERT INTO _ledger_meta(key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying sqlite connection."""
        self._conn.close()

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Writers
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_prompt(prompt: str) -> str:
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    @_retry_on_transient
    def log_query(self, prompt: str, domain: str = "generic") -> int:
        """Insert a query row and return its new id."""
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO queries(prompt_hash, prompt, domain) VALUES (?, ?, ?)",
                (self._hash_prompt(prompt), prompt, domain),
            )
            qid = cur.lastrowid
        _LOG.debug("ledger.query.logged", query_id=qid, domain=domain)
        return qid  # type: ignore[return-value]

    @_retry_on_transient
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
        """Insert an answer row tied to *query_id* and return its new id."""
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO answers(query_id, model, backend, tier, answer, latency_ms, cost)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (query_id, model, backend, tier, answer, latency_ms, cost),
            )
            return cur.lastrowid or 0

    @_retry_on_transient
    def log_score(self, answer_id: int, method: str, value: float) -> int:
        """Insert a UQ score for *answer_id* and return its new id."""
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO uq_scores(answer_id, method, value) VALUES (?, ?, ?)",
                (answer_id, method, float(value)),
            )
            return cur.lastrowid  # type: ignore[return-value]

    @_retry_on_transient
    def log_policy(
        self,
        answer_id: int,
        decision: str,
        threshold: float,
        passed: bool,
        reason: str = "",
    ) -> int:
        """Insert a policy decision for *answer_id* and return its new id."""
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO policy_decisions(answer_id, decision, threshold, passed, reason)"
                " VALUES (?, ?, ?, ?, ?)",
                (answer_id, decision, float(threshold), int(bool(passed)), reason),
            )
            return cur.lastrowid  # type: ignore[return-value]

    @_retry_on_transient
    def update_outcome(
        self,
        answer_id: int,
        *,
        correct: bool,
        ground_truth: str | None = None,
        human_verdict: str | None = None,
    ) -> None:
        """Upsert the labelled outcome for *answer_id*."""
        with self._tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO outcomes(answer_id, ground_truth, human_verdict, correct)"
                " VALUES (?, ?, ?, ?)",
                (answer_id, ground_truth, human_verdict, int(bool(correct))),
            )

    # ------------------------------------------------------------------
    # Readers
    # ------------------------------------------------------------------

    def fetch_answer(self, answer_id: int) -> dict[str, Any] | None:
        """Return the answer row as a dict, or ``None`` if not found."""
        row = self._conn.execute("SELECT * FROM answers WHERE id = ?", (answer_id,)).fetchone()
        return dict(row) if row else None

    def fetch_scores(self, answer_id: int) -> list[dict[str, Any]]:
        """Return all ``(method, value)`` UQ scores recorded for *answer_id*."""
        return [
            dict(r)
            for r in self._conn.execute(
                "SELECT method, value FROM uq_scores WHERE answer_id = ?",
                (answer_id,),
            ).fetchall()
        ]

    def summary(self) -> LedgerSummary:
        """Return aggregate counts derived from the current ledger state.

        Backend-agnostic API used by :mod:`lub.ledger.metrics` to render
        Prometheus / Grafana payloads. Replaces the previous pattern of
        reaching into the sqlite-specific ``_conn`` attribute, so any
        :class:`~lub.ledger.protocol.LedgerProtocol` implementation
        (including the in-memory test double) can drive the same
        exporter.
        """
        c = self._conn
        n_answers = int(c.execute("SELECT COUNT(*) FROM answers").fetchone()[0])
        n_scored = int(c.execute("SELECT COUNT(*) FROM uq_scores").fetchone()[0])
        n_outcomes = int(c.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0])
        n_correct = int(c.execute("SELECT COALESCE(SUM(correct), 0) FROM outcomes").fetchone()[0])
        n_decisions = int(c.execute("SELECT COUNT(*) FROM policy_decisions").fetchone()[0])
        n_abstain = int(
            c.execute(
                "SELECT COUNT(*) FROM policy_decisions WHERE decision = 'abstain'"
            ).fetchone()[0]
        )
        tier_counts: dict[str, int] = {}
        for r in c.execute(
            "SELECT COALESCE(tier, model) AS label, COUNT(*) AS n FROM answers GROUP BY label"
        ).fetchall():
            tier_counts[str(r["label"])] = int(r["n"])
        distinct_methods = sorted(
            str(r["method"]) for r in c.execute("SELECT DISTINCT method FROM uq_scores").fetchall()
        )
        return LedgerSummary(
            n_answers=n_answers,
            n_scored=n_scored,
            n_outcomes=n_outcomes,
            n_correct=n_correct,
            n_policy_decisions=n_decisions,
            n_abstain=n_abstain,
            tier_counts=tier_counts,
            distinct_methods=distinct_methods,
        )

    def replay_calibration(
        self,
        method: str = "confidence",
        n_buckets: int = 10,
    ) -> list[CalibrationPoint]:
        """Return reliability-diagram buckets for *method*.

        Joins ``uq_scores`` against ``outcomes`` so only labelled
        answers contribute. A bucket with zero labelled answers is
        returned with ``n == 0`` and NaN-safe zero values so plotting
        code can still render the axis.
        """
        if n_buckets <= 0:
            raise ValueError(f"n_buckets must be positive, got {n_buckets}")
        rows = self._conn.execute(
            "SELECT u.value AS conf, o.correct AS correct"
            " FROM uq_scores u"
            " JOIN outcomes o ON o.answer_id = u.answer_id"
            " WHERE u.method = ?",
            (method,),
        ).fetchall()

        width = 1.0 / n_buckets
        buckets: list[list[tuple[float, int]]] = [[] for _ in range(n_buckets)]
        for r in rows:
            conf = float(r["conf"])
            conf = min(max(conf, 0.0), 1.0)
            idx = min(int(conf / width), n_buckets - 1)
            buckets[idx].append((conf, int(r["correct"])))

        out: list[CalibrationPoint] = []
        for i, entries in enumerate(buckets):
            lo = i * width
            hi = (i + 1) * width if i < n_buckets - 1 else 1.0
            if not entries:
                out.append(CalibrationPoint(i, lo, hi, 0.0, 0.0, 0))
                continue
            mean_conf = sum(e[0] for e in entries) / len(entries)
            acc = sum(e[1] for e in entries) / len(entries)
            out.append(CalibrationPoint(i, lo, hi, mean_conf, acc, len(entries)))
        return out


__all__ = ["CalibrationPoint", "Ledger"]
