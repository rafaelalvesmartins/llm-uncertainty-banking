# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""Tests for lub.dashboard.ledger_source.

Exercises :class:`LedgerSnapshotSource` and :func:`iso_timestamp` against a
real in-memory sqlite database seeded with the schema-v3 tables the source
queries: ``queries``, ``answers``, ``outcomes``, ``policy_decisions``,
``cec_meta_predictions``, ``cec_meta_outcomes``. Using a real sqlite handle
(rather than mocking the cursor) verifies the SQL itself, not just the call
shape.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

import pytest

from lub.dashboard.ledger_source import LedgerSnapshotSource, iso_timestamp

# ---------------------------------------------------------------------------
# Schema helpers and fixtures
# ---------------------------------------------------------------------------


_SCHEMA_SQL = """
CREATE TABLE queries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_hash TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    domain      TEXT NOT NULL DEFAULT 'generic',
    created_at  TEXT NOT NULL
);

CREATE TABLE answers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id   INTEGER NOT NULL REFERENCES queries(id),
    model      TEXT NOT NULL,
    backend    TEXT NOT NULL,
    tier       TEXT,
    answer     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE outcomes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_id     INTEGER NOT NULL UNIQUE REFERENCES answers(id),
    correct       INTEGER NOT NULL CHECK (correct IN (0, 1)),
    labelled_at   TEXT NOT NULL
);

CREATE TABLE policy_decisions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_id  INTEGER NOT NULL REFERENCES answers(id),
    decision   TEXT NOT NULL,
    threshold  REAL NOT NULL,
    passed     INTEGER NOT NULL CHECK (passed IN (0, 1)),
    reason     TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE cec_meta_predictions (
    claim_id             TEXT PRIMARY KEY,
    predicted_confidence REAL NOT NULL,
    horizon_days         INTEGER NOT NULL,
    created_at           TEXT NOT NULL
);

CREATE TABLE cec_meta_outcomes (
    claim_id    TEXT PRIMARY KEY,
    held_up     INTEGER NOT NULL CHECK (held_up IN (0, 1)),
    recorded_at TEXT NOT NULL
);
"""


class _FakeLedger:
    """Minimal stand-in exposing a sqlite ``_conn`` attribute.

    Mirrors the contract :class:`LedgerSnapshotSource` actually depends on
    so tests don't pull :mod:`lub.ledger` in.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn


def _seed_decision(
    conn: sqlite3.Connection,
    *,
    created_at: str,
    passed: int,
    correct: int | None = None,
    domain: str = "banking",
    model: str = "gpt-4o",
    tier: str = "prime",
    decision: str = "EMIT",
    threshold: float = 0.7,
    reason: str = "ok",
) -> int:
    """Insert one query+answer+(optional outcome)+policy_decision row.

    Returns the ``policy_decisions.id`` of the inserted decision row.
    """
    cur = conn.execute(
        "INSERT INTO queries(prompt_hash, prompt, domain, created_at)"
        " VALUES (?, ?, ?, ?)",
        ("h", "Q?", domain, created_at),
    )
    qid = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO answers(query_id, model, backend, tier, answer, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (qid, model, "openai", tier, "a", created_at),
    )
    aid = cur.lastrowid
    if correct is not None:
        conn.execute(
            "INSERT INTO outcomes(answer_id, correct, labelled_at) VALUES (?, ?, ?)",
            (aid, correct, created_at),
        )
    cur = conn.execute(
        "INSERT INTO policy_decisions(answer_id, decision, threshold, passed,"
        " reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (aid, decision, threshold, passed, reason, created_at),
    )
    return cur.lastrowid


def _seed_meta_claim(
    conn: sqlite3.Connection,
    *,
    claim_id: str,
    predicted_confidence: float,
    held_up: int | None,
    horizon_days: int = 7,
) -> None:
    conn.execute(
        "INSERT INTO cec_meta_predictions(claim_id, predicted_confidence,"
        " horizon_days, created_at) VALUES (?, ?, ?, ?)",
        (claim_id, predicted_confidence, horizon_days, "2026-04-25T00:00:00.000Z"),
    )
    if held_up is not None:
        conn.execute(
            "INSERT INTO cec_meta_outcomes(claim_id, held_up, recorded_at)"
            " VALUES (?, ?, ?)",
            (claim_id, held_up, "2026-04-26T00:00:00.000Z"),
        )


@pytest.fixture
def conn() -> sqlite3.Connection:
    """Fresh in-memory sqlite with row_factory and schema applied."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA_SQL)
    return c


@pytest.fixture
def ledger(conn: sqlite3.Connection) -> _FakeLedger:
    return _FakeLedger(conn)


@pytest.fixture
def source(ledger: _FakeLedger) -> LedgerSnapshotSource:
    return LedgerSnapshotSource(ledger)


@pytest.fixture
def window() -> tuple[datetime, datetime]:
    return datetime(2020, 1, 1), datetime(2030, 1, 1)


# ---------------------------------------------------------------------------
# iso_timestamp
# ---------------------------------------------------------------------------


class TestIsoTimestamp:
    def test_formats_with_z_suffix(self) -> None:
        dt = datetime(2026, 4, 25, 12, 30, 45, 123456)
        assert iso_timestamp(dt) == "2026-04-25T12:30:45.123Z"

    def test_truncates_microseconds_to_milliseconds(self) -> None:
        dt = datetime(2026, 1, 1, 0, 0, 0, 999999)
        out = iso_timestamp(dt)
        assert out.endswith(".999Z")
        assert "999999" not in out

    def test_zero_microseconds_padded(self) -> None:
        dt = datetime(2026, 1, 1, 0, 0, 0, 0)
        assert iso_timestamp(dt) == "2026-01-01T00:00:00.000Z"

    def test_sorts_lexicographically(self) -> None:
        a = iso_timestamp(datetime(2026, 4, 25, 12, 0, 0))
        b = iso_timestamp(datetime(2026, 4, 25, 12, 0, 1))
        assert a < b


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_accepts_object_with_conn_attribute(
        self, ledger: _FakeLedger, conn: sqlite3.Connection
    ) -> None:
        src = LedgerSnapshotSource(ledger)
        assert src._conn is conn

    def test_rejects_object_without_conn(self) -> None:
        with pytest.raises(TypeError, match="_conn"):
            LedgerSnapshotSource(object())

    def test_rejects_when_conn_is_none(self) -> None:
        class HasNoneConn:
            _conn = None

        with pytest.raises(TypeError, match="_conn"):
            LedgerSnapshotSource(HasNoneConn())

    def test_keeps_ledger_reference(self, ledger: _FakeLedger) -> None:
        src = LedgerSnapshotSource(ledger)
        assert src._ledger is ledger

    def test_type_error_message_includes_typename(self) -> None:
        with pytest.raises(TypeError, match="object"):
            LedgerSnapshotSource(object())


# ---------------------------------------------------------------------------
# kpi_decisions
# ---------------------------------------------------------------------------


class TestKpiDecisions:
    def test_empty_window_returns_zero_and_zero_rate(
        self, source: LedgerSnapshotSource, window: tuple[datetime, datetime]
    ) -> None:
        n, rate = source.kpi_decisions(*window)
        assert n == 0
        assert rate == 0.0

    def test_counts_decisions_in_window(
        self,
        conn: sqlite3.Connection,
        source: LedgerSnapshotSource,
        window: tuple[datetime, datetime],
    ) -> None:
        _seed_decision(conn, created_at="2026-04-25T10:00:00.000Z", passed=1)
        _seed_decision(conn, created_at="2026-04-25T11:00:00.000Z", passed=1)
        n, rate = source.kpi_decisions(*window)
        assert n == 2
        assert rate == 0.0

    def test_abstention_rate_half(
        self,
        conn: sqlite3.Connection,
        source: LedgerSnapshotSource,
        window: tuple[datetime, datetime],
    ) -> None:
        _seed_decision(conn, created_at="2026-04-25T10:00:00.000Z", passed=1)
        _seed_decision(conn, created_at="2026-04-25T11:00:00.000Z", passed=0)
        n, rate = source.kpi_decisions(*window)
        assert n == 2
        assert rate == pytest.approx(0.5)

    def test_all_abstained(
        self,
        conn: sqlite3.Connection,
        source: LedgerSnapshotSource,
        window: tuple[datetime, datetime],
    ) -> None:
        _seed_decision(conn, created_at="2026-04-25T10:00:00.000Z", passed=0)
        _seed_decision(conn, created_at="2026-04-25T11:00:00.000Z", passed=0)
        n, rate = source.kpi_decisions(*window)
        assert n == 2
        assert rate == pytest.approx(1.0)

    def test_filters_out_decisions_outside_window(
        self, conn: sqlite3.Connection, source: LedgerSnapshotSource
    ) -> None:
        _seed_decision(conn, created_at="2019-01-01T00:00:00.000Z", passed=0)
        _seed_decision(conn, created_at="2026-04-25T10:00:00.000Z", passed=1)
        _seed_decision(conn, created_at="2031-01-01T00:00:00.000Z", passed=0)
        n, _ = source.kpi_decisions(datetime(2026, 1, 1), datetime(2026, 12, 31))
        assert n == 1

    def test_boundary_timestamps_inclusive(
        self, conn: sqlite3.Connection, source: LedgerSnapshotSource
    ) -> None:
        start = datetime(2026, 4, 25, 12, 0, 0)
        end = datetime(2026, 4, 25, 13, 0, 0)
        _seed_decision(conn, created_at=iso_timestamp(start), passed=1)
        _seed_decision(conn, created_at=iso_timestamp(end), passed=1)
        n, _ = source.kpi_decisions(start, end)
        assert n == 2


# ---------------------------------------------------------------------------
# kpi_outcomes
# ---------------------------------------------------------------------------


class TestKpiOutcomes:
    def test_empty_window_returns_none_rate(
        self, source: LedgerSnapshotSource, window: tuple[datetime, datetime]
    ) -> None:
        n, rate = source.kpi_outcomes(*window)
        assert n == 0
        assert rate is None

    def test_all_correct(
        self,
        conn: sqlite3.Connection,
        source: LedgerSnapshotSource,
        window: tuple[datetime, datetime],
    ) -> None:
        _seed_decision(conn, created_at="2026-04-25T10:00:00.000Z", passed=1, correct=1)
        _seed_decision(conn, created_at="2026-04-25T11:00:00.000Z", passed=1, correct=1)
        n, rate = source.kpi_outcomes(*window)
        assert n == 2
        assert rate == pytest.approx(1.0)

    def test_mixed_correctness(
        self,
        conn: sqlite3.Connection,
        source: LedgerSnapshotSource,
        window: tuple[datetime, datetime],
    ) -> None:
        _seed_decision(conn, created_at="2026-04-25T10:00:00.000Z", passed=1, correct=1)
        _seed_decision(conn, created_at="2026-04-25T11:00:00.000Z", passed=1, correct=0)
        _seed_decision(conn, created_at="2026-04-25T12:00:00.000Z", passed=1, correct=1)
        n, rate = source.kpi_outcomes(*window)
        assert n == 3
        assert rate == pytest.approx(2 / 3)

    def test_ignores_decisions_without_outcomes(
        self,
        conn: sqlite3.Connection,
        source: LedgerSnapshotSource,
        window: tuple[datetime, datetime],
    ) -> None:
        _seed_decision(conn, created_at="2026-04-25T10:00:00.000Z", passed=1, correct=None)
        _seed_decision(conn, created_at="2026-04-25T11:00:00.000Z", passed=1, correct=1)
        n, rate = source.kpi_outcomes(*window)
        assert n == 1
        assert rate == pytest.approx(1.0)

    def test_none_rate_disambiguates_from_zero(
        self,
        conn: sqlite3.Connection,
        source: LedgerSnapshotSource,
        window: tuple[datetime, datetime],
    ) -> None:
        n_empty, rate_empty = source.kpi_outcomes(*window)
        _seed_decision(conn, created_at="2026-04-25T10:00:00.000Z", passed=1, correct=0)
        n_zero, rate_zero = source.kpi_outcomes(*window)
        assert rate_empty is None
        assert rate_zero == pytest.approx(0.0)
        assert n_empty == 0
        assert n_zero == 1


# ---------------------------------------------------------------------------
# kpi_meta_calibration_ece
# ---------------------------------------------------------------------------


class TestKpiMetaCalibrationEce:
    def test_no_claims_returns_none(self, source: LedgerSnapshotSource) -> None:
        assert source.kpi_meta_calibration_ece() is None

    def test_predictions_without_outcomes_returns_none(
        self, conn: sqlite3.Connection, source: LedgerSnapshotSource
    ) -> None:
        _seed_meta_claim(conn, claim_id="c1", predicted_confidence=0.8, held_up=None)
        assert source.kpi_meta_calibration_ece() is None

    def test_perfectly_calibrated_yields_zero(
        self, conn: sqlite3.Connection, source: LedgerSnapshotSource
    ) -> None:
        for i in range(10):
            _seed_meta_claim(conn, claim_id=f"a{i}", predicted_confidence=0.0, held_up=0)
        for i in range(10):
            _seed_meta_claim(conn, claim_id=f"b{i}", predicted_confidence=1.0, held_up=1)
        assert source.kpi_meta_calibration_ece() == pytest.approx(0.0)

    def test_maximally_miscalibrated_yields_one(
        self, conn: sqlite3.Connection, source: LedgerSnapshotSource
    ) -> None:
        _seed_meta_claim(conn, claim_id="c1", predicted_confidence=1.0, held_up=0)
        assert source.kpi_meta_calibration_ece() == pytest.approx(1.0)

    def test_confidence_above_one_clipped(
        self, conn: sqlite3.Connection, source: LedgerSnapshotSource
    ) -> None:
        _seed_meta_claim(conn, claim_id="c1", predicted_confidence=1.5, held_up=1)
        assert source.kpi_meta_calibration_ece() == pytest.approx(0.0)

    def test_confidence_below_zero_clipped(
        self, conn: sqlite3.Connection, source: LedgerSnapshotSource
    ) -> None:
        _seed_meta_claim(conn, claim_id="c1", predicted_confidence=-0.5, held_up=0)
        assert source.kpi_meta_calibration_ece() == pytest.approx(0.0)

    def test_respects_n_buckets_argument(
        self, conn: sqlite3.Connection, source: LedgerSnapshotSource
    ) -> None:
        # Two claims in same bin with 5 buckets, different bins with 50.
        _seed_meta_claim(conn, claim_id="c1", predicted_confidence=0.10, held_up=1)
        _seed_meta_claim(conn, claim_id="c2", predicted_confidence=0.19, held_up=0)
        ece_5 = source.kpi_meta_calibration_ece(n_buckets=5)
        ece_50 = source.kpi_meta_calibration_ece(n_buckets=50)
        assert ece_5 is not None and ece_50 is not None
        assert ece_5 != ece_50


# ---------------------------------------------------------------------------
# recent_decisions
# ---------------------------------------------------------------------------


class TestRecentDecisions:
    def test_empty_window_returns_empty_list(
        self, source: LedgerSnapshotSource, window: tuple[datetime, datetime]
    ) -> None:
        assert source.recent_decisions(*window) == []

    def test_returns_expected_keys(
        self,
        conn: sqlite3.Connection,
        source: LedgerSnapshotSource,
        window: tuple[datetime, datetime],
    ) -> None:
        _seed_decision(
            conn,
            created_at="2026-04-25T10:00:00.000Z",
            passed=1,
            domain="payments",
            model="gpt-4o",
            tier="prime",
            decision="EMIT",
            reason="ok",
        )
        rows = source.recent_decisions(*window)
        assert len(rows) == 1
        expected = {
            "id", "decision", "threshold", "passed", "reason",
            "created_at", "model", "tier", "domain",
        }
        assert expected.issubset(rows[0].keys())
        assert rows[0]["domain"] == "payments"
        assert rows[0]["model"] == "gpt-4o"
        assert rows[0]["tier"] == "prime"
        assert rows[0]["decision"] == "EMIT"
        assert rows[0]["passed"] == 1

    def test_ordered_newest_first(
        self,
        conn: sqlite3.Connection,
        source: LedgerSnapshotSource,
        window: tuple[datetime, datetime],
    ) -> None:
        _seed_decision(conn, created_at="2026-04-25T09:00:00.000Z", passed=1, reason="old")
        _seed_decision(conn, created_at="2026-04-25T12:00:00.000Z", passed=1, reason="new")
        _seed_decision(conn, created_at="2026-04-25T10:30:00.000Z", passed=1, reason="mid")
        rows = source.recent_decisions(*window)
        assert [r["reason"] for r in rows] == ["new", "mid", "old"]

    def test_limit_caps_results(
        self,
        conn: sqlite3.Connection,
        source: LedgerSnapshotSource,
        window: tuple[datetime, datetime],
    ) -> None:
        for i in range(5):
            _seed_decision(conn, created_at=f"2026-04-25T1{i}:00:00.000Z", passed=1)
        rows = source.recent_decisions(*window, limit=2)
        assert len(rows) == 2

    def test_default_limit_is_25(
        self,
        conn: sqlite3.Connection,
        source: LedgerSnapshotSource,
        window: tuple[datetime, datetime],
    ) -> None:
        for i in range(30):
            _seed_decision(conn, created_at=f"2026-04-25T{i:02d}:00:00.000Z", passed=1)
        rows = source.recent_decisions(*window)
        assert len(rows) == 25

    def test_limit_zero_returns_empty(
        self,
        conn: sqlite3.Connection,
        source: LedgerSnapshotSource,
        window: tuple[datetime, datetime],
    ) -> None:
        _seed_decision(conn, created_at="2026-04-25T10:00:00.000Z", passed=1)
        assert source.recent_decisions(*window, limit=0) == []

    def test_filters_out_decisions_outside_window(
        self, conn: sqlite3.Connection, source: LedgerSnapshotSource
    ) -> None:
        _seed_decision(conn, created_at="2019-01-01T00:00:00.000Z", passed=1, reason="before")
        _seed_decision(conn, created_at="2026-04-25T10:00:00.000Z", passed=1, reason="inside")
        rows = source.recent_decisions(
            datetime(2026, 1, 1), datetime(2026, 12, 31)
        )
        reasons = [r["reason"] for r in rows]
        assert reasons == ["inside"]

    def test_returns_plain_dicts(
        self,
        conn: sqlite3.Connection,
        source: LedgerSnapshotSource,
        window: tuple[datetime, datetime],
    ) -> None:
        _seed_decision(conn, created_at="2026-04-25T10:00:00.000Z", passed=1)
        rows = source.recent_decisions(*window)
        assert all(isinstance(r, dict) for r in rows)


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    def test_corrupt_conn_propagates_sqlite_error(
        self, window: tuple[datetime, datetime]
    ) -> None:
        # Connection with no schema -> "no such table" error bubbles up.
        bare = sqlite3.connect(":memory:")
        bare.row_factory = sqlite3.Row
        src = LedgerSnapshotSource(_FakeLedger(bare))
        with pytest.raises(sqlite3.OperationalError):
            src.kpi_decisions(*window)

    def test_closed_conn_propagates_error(
        self,
        conn: sqlite3.Connection,
        ledger: _FakeLedger,
        window: tuple[datetime, datetime],
    ) -> None:
        src = LedgerSnapshotSource(ledger)
        conn.close()
        with pytest.raises(sqlite3.ProgrammingError):
            src.kpi_decisions(*window)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_satisfies_snapshot_source_protocol(
        self, source: LedgerSnapshotSource
    ) -> None:
        from lub.dashboard.protocols import SnapshotSource

        assert isinstance(source, SnapshotSource)

    def test_kpi_decisions_signature_matches_protocol(
        self, source: LedgerSnapshotSource, window: tuple[datetime, datetime]
    ) -> None:
        result = source.kpi_decisions(*window)
        assert isinstance(result, tuple)
        assert len(result) == 2
        n, rate = result
        assert isinstance(n, int)
        assert isinstance(rate, float)

    def test_kpi_outcomes_signature_matches_protocol(
        self, source: LedgerSnapshotSource, window: tuple[datetime, datetime]
    ) -> None:
        n, rate = source.kpi_outcomes(*window)
        assert isinstance(n, int)
        assert rate is None or isinstance(rate, float)

    def test_recent_decisions_returns_list_of_dicts(
        self,
        conn: sqlite3.Connection,
        source: LedgerSnapshotSource,
        window: tuple[datetime, datetime],
    ) -> None:
        _seed_decision(conn, created_at="2026-04-25T10:00:00.000Z", passed=1)
        result: list[dict[str, Any]] = source.recent_decisions(*window)
        assert isinstance(result, list)
        assert isinstance(result[0], dict)
