# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for LedgerSummary + LedgerProtocol.summary().

Covers:
- The dataclass shape (LedgerSummary).
- Ledger.summary() on the sqlite backend with realistic state.
- InMemoryLedger.summary() returning the same shape.
- lub.ledger.metrics.collect_metrics consuming summary() correctly,
  no longer reaching into ``Ledger._conn``.
"""

from __future__ import annotations

from lub.ledger import Ledger
from lub.ledger.metrics import collect_metrics
from lub.ledger.protocol import InMemoryLedger, LedgerProtocol, LedgerSummary

# ---------------------------------------------------------------------------
# LedgerSummary dataclass
# ---------------------------------------------------------------------------


def test_ledger_summary_default_factories() -> None:
    """Default tier_counts / distinct_methods are independent per instance."""
    a = LedgerSummary(0, 0, 0, 0, 0, 0)
    b = LedgerSummary(0, 0, 0, 0, 0, 0)
    a.tier_counts["x"] = 1
    a.distinct_methods.append("y")
    assert b.tier_counts == {}
    assert b.distinct_methods == []


# ---------------------------------------------------------------------------
# Sqlite Ledger.summary()
# ---------------------------------------------------------------------------


def test_sqlite_ledger_summary_empty() -> None:
    with Ledger(":memory:") as ledger:
        s = ledger.summary()
    assert s.n_answers == 0
    assert s.n_scored == 0
    assert s.n_outcomes == 0
    assert s.n_correct == 0
    assert s.n_policy_decisions == 0
    assert s.n_abstain == 0
    assert s.tier_counts == {}
    assert s.distinct_methods == []


def test_sqlite_ledger_summary_after_writes() -> None:
    with Ledger(":memory:") as ledger:
        q1 = ledger.log_query("what is CET1?", domain="banking")
        q2 = ledger.log_query("hello?", domain="generic")
        a1 = ledger.log_answer(q1, model="m1", backend="dummy", answer="A1", tier="cheap")
        a2 = ledger.log_answer(q1, model="m1", backend="dummy", answer="A2", tier="cheap")
        _a3 = ledger.log_answer(q2, model="m1", backend="dummy", answer="A3")  # tier=None -> falls back to model
        ledger.log_score(a1, "confidence", 0.9)
        ledger.log_score(a2, "confidence", 0.4)
        ledger.log_score(a2, "p_true", 0.5)
        ledger.update_outcome(a1, correct=True)
        ledger.update_outcome(a2, correct=False)
        ledger.log_policy(a1, decision="emit", threshold=0.5, passed=True)
        ledger.log_policy(a2, decision="abstain", threshold=0.5, passed=False)

        s = ledger.summary()

    assert s.n_answers == 3
    assert s.n_scored == 3
    assert s.n_outcomes == 2
    assert s.n_correct == 1
    assert s.n_policy_decisions == 2
    assert s.n_abstain == 1
    # Tier coalesce: tier when set, else model.
    assert s.tier_counts == {"cheap": 2, "m1": 1}
    assert s.distinct_methods == ["confidence", "p_true"]


# ---------------------------------------------------------------------------
# InMemoryLedger.summary() agrees structurally
# ---------------------------------------------------------------------------


def test_in_memory_ledger_summary_matches_shape() -> None:
    ledger = InMemoryLedger()
    q = ledger.log_query("q", domain="banking")
    a = ledger.log_answer(q, model="m1", backend="hf", answer="A", tier="t1")
    ledger.log_score(a, "confidence", 0.7)
    ledger.update_outcome(a, correct=True)
    ledger.log_policy(a, decision="abstain", threshold=0.5, passed=False)

    s = ledger.summary()
    assert isinstance(s, LedgerSummary)
    assert s.n_answers == 1
    assert s.n_scored == 1
    assert s.n_outcomes == 1
    assert s.n_correct == 1
    assert s.n_policy_decisions == 1
    assert s.n_abstain == 1
    assert s.tier_counts == {"t1": 1}
    assert s.distinct_methods == ["confidence"]


def test_in_memory_ledger_satisfies_protocol() -> None:
    """runtime_checkable Protocol -- isinstance must agree."""
    ledger = InMemoryLedger()
    assert isinstance(ledger, LedgerProtocol)


def test_sqlite_ledger_satisfies_protocol() -> None:
    with Ledger(":memory:") as ledger:
        assert isinstance(ledger, LedgerProtocol)


# ---------------------------------------------------------------------------
# collect_metrics no longer needs ``ledger._conn``
# ---------------------------------------------------------------------------


def test_collect_metrics_works_against_in_memory_ledger() -> None:
    """The exporter must drive the in-memory test double too. Pre-refactor
    this would have crashed inside ``ledger._conn.execute(...)``."""
    ledger = InMemoryLedger()
    q = ledger.log_query("q", domain="banking")
    a = ledger.log_answer(q, model="m", backend="hf", answer="A")
    ledger.log_score(a, "confidence", 0.8)
    ledger.update_outcome(a, correct=True)

    m = collect_metrics(ledger)
    assert m.n_answers == 1
    assert m.n_scored == 1
    assert m.n_outcomes == 1
    assert m.accuracy == 1.0
    # In-memory ledger does not implement replay_calibration; exporter
    # gracefully skips ECE rather than crashing.
    assert m.ece_by_method == {}


def test_collect_metrics_works_against_sqlite_ledger() -> None:
    with Ledger(":memory:") as ledger:
        q = ledger.log_query("q", domain="banking")
        a = ledger.log_answer(q, model="m", backend="dummy", answer="A")
        ledger.log_score(a, "confidence", 0.6)
        ledger.update_outcome(a, correct=False)

        m = collect_metrics(ledger)

    assert m.n_answers == 1
    assert m.n_outcomes == 1
    assert m.accuracy == 0.0
