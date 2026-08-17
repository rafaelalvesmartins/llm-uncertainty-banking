# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""Tests for lub.dashboard.in_memory_source.

Exercises the InMemorySnapshotSource bridge that exposes an
:class:`~lub.ledger.protocol.InMemoryLedger`-shaped object as a
:class:`~lub.dashboard.protocols.SnapshotSource`. Tests use
SimpleNamespace fakes that mirror the ledger's internal-list shape,
so they neither depend on sqlite nor on InMemoryLedger's public API.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from lub.dashboard.in_memory_source import InMemorySnapshotSource

# -- Helpers / fixtures ----------------------------------------------------


def _make_ledger(
    queries: list[dict[str, Any]] | None = None,
    answers: list[dict[str, Any]] | None = None,
    policies: list[dict[str, Any]] | None = None,
    outcomes: dict[Any, dict[str, Any]] | None = None,
) -> SimpleNamespace:
    """Build a fake matching the InMemoryLedger internal-list shape."""
    return SimpleNamespace(
        _queries=list(queries or []),
        _answers=list(answers or []),
        _scores=[],
        _policies=list(policies or []),
        _outcomes=dict(outcomes or {}),
    )


@pytest.fixture
def empty_ledger() -> SimpleNamespace:
    return _make_ledger()


@pytest.fixture
def window() -> tuple[datetime, datetime]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 12, 31, tzinfo=UTC)
    return start, end


@pytest.fixture
def populated_ledger() -> SimpleNamespace:
    """Ledger with three Q→A→Policy chains and matching outcomes.

    * 2 of 3 policies passed → abstention rate = 1/3
    * 2 of 3 outcomes correct → correctness rate = 2/3
    """
    queries = [
        {"id": 1, "text": "Q1?", "domain": "banking"},
        {"id": 2, "text": "Q2?", "domain": "kyc"},
        {"id": 3, "text": "Q3?", "domain": "banking"},
    ]
    answers = [
        {"id": 10, "query_id": 1, "model": "gpt-4o", "tier": "prime"},
        {"id": 11, "query_id": 2, "model": "gpt-3.5", "tier": "standard"},
        {"id": 12, "query_id": 3, "model": "claude-4-7", "tier": "prime"},
    ]
    policies = [
        {"id": 100, "answer_id": 10, "decision": "EMIT",
         "threshold": 0.7, "passed": True, "reason": "ok"},
        {"id": 101, "answer_id": 11, "decision": "ABSTAIN",
         "threshold": 0.7, "passed": False, "reason": "low conf"},
        {"id": 102, "answer_id": 12, "decision": "EMIT",
         "threshold": 0.7, "passed": True, "reason": "ok"},
    ]
    outcomes = {
        10: {"correct": True},
        11: {"correct": False},
        12: {"correct": True},
    }
    return _make_ledger(queries, answers, policies, outcomes)


# -- __init__ --------------------------------------------------------------


class TestInit:
    def test_accepts_valid_ledger(self, empty_ledger: SimpleNamespace) -> None:
        source = InMemorySnapshotSource(empty_ledger)
        assert source is not None

    @pytest.mark.parametrize(
        "missing_attr",
        ["_queries", "_answers", "_policies", "_outcomes"],
    )
    def test_rejects_ledger_missing_required_attribute(
        self, missing_attr: str
    ) -> None:
        ledger = _make_ledger()
        delattr(ledger, missing_attr)
        with pytest.raises(TypeError, match=missing_attr):
            InMemorySnapshotSource(ledger)

    def test_rejects_plain_object(self) -> None:
        with pytest.raises(TypeError):
            InMemorySnapshotSource(object())

    def test_error_message_names_offending_type(self) -> None:
        ledger = _make_ledger()
        delattr(ledger, "_policies")
        with pytest.raises(TypeError, match="SimpleNamespace"):
            InMemorySnapshotSource(ledger)


# -- kpi_decisions ---------------------------------------------------------


class TestKpiDecisions:
    def test_empty_ledger_returns_zero_zero(
        self,
        empty_ledger: SimpleNamespace,
        window: tuple[datetime, datetime],
    ) -> None:
        source = InMemorySnapshotSource(empty_ledger)
        assert source.kpi_decisions(*window) == (0, 0.0)

    def test_counts_and_abstention_rate(
        self,
        populated_ledger: SimpleNamespace,
        window: tuple[datetime, datetime],
    ) -> None:
        source = InMemorySnapshotSource(populated_ledger)
        n, abst_rate = source.kpi_decisions(*window)
        assert n == 3
        assert abst_rate == pytest.approx(1 / 3)

    def test_all_passed_yields_zero_abstention(
        self, window: tuple[datetime, datetime]
    ) -> None:
        ledger = _make_ledger(
            policies=[
                {"id": 1, "answer_id": 1, "passed": True},
                {"id": 2, "answer_id": 1, "passed": True},
            ]
        )
        assert InMemorySnapshotSource(ledger).kpi_decisions(*window) == (2, 0.0)

    def test_all_failed_yields_full_abstention(
        self, window: tuple[datetime, datetime]
    ) -> None:
        ledger = _make_ledger(
            policies=[
                {"id": 1, "answer_id": 1, "passed": False},
                {"id": 2, "answer_id": 1, "passed": False},
            ]
        )
        assert InMemorySnapshotSource(ledger).kpi_decisions(*window) == (2, 1.0)

    def test_time_window_is_ignored(
        self, populated_ledger: SimpleNamespace
    ) -> None:
        # No per-row timestamps → window must not filter anything out.
        source = InMemorySnapshotSource(populated_ledger)
        narrow = datetime(1900, 1, 1, tzinfo=UTC)
        wide = datetime(2100, 1, 1, tzinfo=UTC)
        n_collapsed, _ = source.kpi_decisions(narrow, narrow)
        n_open, _ = source.kpi_decisions(narrow, wide)
        assert n_collapsed == n_open == 3

    def test_missing_passed_treated_as_falsy(
        self, window: tuple[datetime, datetime]
    ) -> None:
        # `.get("passed")` returns None when absent; None is falsy, so the
        # decision counts as an abstention. Pin this behavior.
        ledger = _make_ledger(
            policies=[{"id": 1, "answer_id": 1}]  # no "passed" key
        )
        n, abst = InMemorySnapshotSource(ledger).kpi_decisions(*window)
        assert (n, abst) == (1, 1.0)


# -- kpi_outcomes ----------------------------------------------------------


class TestKpiOutcomes:
    def test_empty_outcomes_returns_zero_none(
        self,
        empty_ledger: SimpleNamespace,
        window: tuple[datetime, datetime],
    ) -> None:
        # Returning None (not 0.0) is the contract: dashboard renders
        # "no data" instead of a misleading 0% correctness.
        source = InMemorySnapshotSource(empty_ledger)
        assert source.kpi_outcomes(*window) == (0, None)

    def test_counts_and_correctness_rate(
        self,
        populated_ledger: SimpleNamespace,
        window: tuple[datetime, datetime],
    ) -> None:
        source = InMemorySnapshotSource(populated_ledger)
        n, rate = source.kpi_outcomes(*window)
        assert n == 3
        assert rate == pytest.approx(2 / 3)

    def test_all_correct(self, window: tuple[datetime, datetime]) -> None:
        ledger = _make_ledger(
            outcomes={1: {"correct": True}, 2: {"correct": True}}
        )
        assert InMemorySnapshotSource(ledger).kpi_outcomes(*window) == (2, 1.0)

    def test_all_incorrect(self, window: tuple[datetime, datetime]) -> None:
        ledger = _make_ledger(
            outcomes={1: {"correct": False}, 2: {"correct": False}}
        )
        assert InMemorySnapshotSource(ledger).kpi_outcomes(*window) == (2, 0.0)

    def test_missing_correct_field_treated_as_falsy(
        self, window: tuple[datetime, datetime]
    ) -> None:
        ledger = _make_ledger(outcomes={1: {}, 2: {"correct": True}})
        n, rate = InMemorySnapshotSource(ledger).kpi_outcomes(*window)
        assert n == 2
        assert rate == pytest.approx(0.5)


# -- kpi_meta_calibration_ece ----------------------------------------------


class TestKpiMetaCalibrationEce:
    def test_returns_none_when_populated(
        self, populated_ledger: SimpleNamespace
    ) -> None:
        # In-memory ledger has no CEC table → must always return None.
        assert InMemorySnapshotSource(populated_ledger).kpi_meta_calibration_ece() is None

    def test_returns_none_when_empty(
        self, empty_ledger: SimpleNamespace
    ) -> None:
        assert InMemorySnapshotSource(empty_ledger).kpi_meta_calibration_ece() is None


# -- recent_decisions ------------------------------------------------------


class TestRecentDecisions:
    def test_empty_returns_empty_list(
        self,
        empty_ledger: SimpleNamespace,
        window: tuple[datetime, datetime],
    ) -> None:
        assert InMemorySnapshotSource(empty_ledger).recent_decisions(*window) == []

    def test_row_shape_matches_sqlite_source(
        self,
        populated_ledger: SimpleNamespace,
        window: tuple[datetime, datetime],
    ) -> None:
        rows = InMemorySnapshotSource(populated_ledger).recent_decisions(*window)
        expected_keys = {
            "id", "decision", "threshold", "passed", "reason",
            "created_at", "model", "tier", "domain",
        }
        assert len(rows) == 3
        for row in rows:
            assert set(row.keys()) == expected_keys
            assert row["created_at"] == "in-memory"

    def test_reverse_insertion_order(
        self,
        populated_ledger: SimpleNamespace,
        window: tuple[datetime, datetime],
    ) -> None:
        rows = InMemorySnapshotSource(populated_ledger).recent_decisions(*window)
        assert [r["id"] for r in rows] == [102, 101, 100]

    def test_respects_explicit_limit(
        self,
        populated_ledger: SimpleNamespace,
        window: tuple[datetime, datetime],
    ) -> None:
        rows = InMemorySnapshotSource(populated_ledger).recent_decisions(*window, limit=2)
        assert len(rows) == 2
        assert [r["id"] for r in rows] == [102, 101]

    def test_default_limit_is_25(
        self, window: tuple[datetime, datetime]
    ) -> None:
        policies = [
            {"id": i, "answer_id": 1, "decision": "EMIT", "passed": True}
            for i in range(50)
        ]
        ledger = _make_ledger(policies=policies)
        rows = InMemorySnapshotSource(ledger).recent_decisions(*window)
        assert len(rows) == 25

    def test_limit_zero_returns_empty(
        self,
        populated_ledger: SimpleNamespace,
        window: tuple[datetime, datetime],
    ) -> None:
        rows = InMemorySnapshotSource(populated_ledger).recent_decisions(*window, limit=0)
        assert rows == []

    def test_limit_larger_than_rows(
        self,
        populated_ledger: SimpleNamespace,
        window: tuple[datetime, datetime],
    ) -> None:
        rows = InMemorySnapshotSource(populated_ledger).recent_decisions(*window, limit=100)
        assert len(rows) == 3

    def test_joins_answer_and_query_fields(
        self,
        populated_ledger: SimpleNamespace,
        window: tuple[datetime, datetime],
    ) -> None:
        rows = InMemorySnapshotSource(populated_ledger).recent_decisions(*window)
        # Most recent: policy 102 → answer 12 → query 3 (domain=banking).
        assert rows[0]["model"] == "claude-4-7"
        assert rows[0]["tier"] == "prime"
        assert rows[0]["domain"] == "banking"
        assert rows[0]["decision"] == "EMIT"
        assert rows[0]["threshold"] == 0.7
        assert rows[0]["passed"] is True
        # Middle: policy 101 → answer 11 → query 2 (domain=kyc).
        assert rows[1]["model"] == "gpt-3.5"
        assert rows[1]["tier"] == "standard"
        assert rows[1]["domain"] == "kyc"
        assert rows[1]["decision"] == "ABSTAIN"
        assert rows[1]["passed"] is False
        assert rows[1]["reason"] == "low conf"

    def test_orphan_policy_with_missing_answer(
        self, window: tuple[datetime, datetime]
    ) -> None:
        ledger = _make_ledger(
            queries=[{"id": 1, "domain": "banking"}],
            answers=[],
            policies=[
                {"id": 1, "answer_id": 99, "decision": "EMIT",
                 "threshold": 0.7, "passed": True, "reason": "ok"}
            ],
        )
        rows = InMemorySnapshotSource(ledger).recent_decisions(*window)
        assert len(rows) == 1
        assert rows[0]["id"] == 1
        assert rows[0]["model"] is None
        assert rows[0]["tier"] is None
        assert rows[0]["domain"] is None

    def test_orphan_answer_with_missing_query(
        self, window: tuple[datetime, datetime]
    ) -> None:
        ledger = _make_ledger(
            queries=[],
            answers=[{"id": 10, "query_id": 999, "model": "gpt-4o", "tier": "prime"}],
            policies=[
                {"id": 1, "answer_id": 10, "decision": "EMIT",
                 "threshold": 0.7, "passed": True, "reason": "ok"}
            ],
        )
        rows = InMemorySnapshotSource(ledger).recent_decisions(*window)
        assert len(rows) == 1
        assert rows[0]["model"] == "gpt-4o"
        assert rows[0]["tier"] == "prime"
        assert rows[0]["domain"] is None

    def test_time_window_is_ignored(
        self, populated_ledger: SimpleNamespace
    ) -> None:
        source = InMemorySnapshotSource(populated_ledger)
        narrow = datetime(1900, 1, 1, tzinfo=UTC)
        rows = source.recent_decisions(narrow, narrow)
        assert len(rows) == 3

    def test_does_not_mutate_underlying_ledger(
        self,
        populated_ledger: SimpleNamespace,
        window: tuple[datetime, datetime],
    ) -> None:
        # `reversed()` over a list yields an iterator without touching
        # the original. Pin this property — the dashboard must not
        # disturb the ledger's insertion order.
        original_policy_ids = [p["id"] for p in populated_ledger._policies]
        InMemorySnapshotSource(populated_ledger).recent_decisions(*window)
        assert [p["id"] for p in populated_ledger._policies] == original_policy_ids
