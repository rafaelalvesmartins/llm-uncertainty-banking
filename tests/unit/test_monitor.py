# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for lub.challenge.context_autopilot.monitor.ContextMonitor."""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import MagicMock

import pytest

from lub.challenge.context_autopilot.monitor import ContextMonitor

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeLedger:
    """Minimal ledger stub exposing the ``_conn`` attribute the monitor uses."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """In-memory SQLite connection with the v3 observations table."""
    c = sqlite3.connect(":memory:")
    c.execute(
        """
        CREATE TABLE context_window_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            turn_id INTEGER NOT NULL,
            input_tokens INTEGER NOT NULL,
            cumulative_tokens INTEGER NOT NULL,
            model_max_context INTEGER NOT NULL,
            headroom_ratio REAL NOT NULL,
            observed_at TEXT NOT NULL
        )
        """
    )
    c.commit()
    return c


@pytest.fixture()
def ledger(conn: sqlite3.Connection) -> _FakeLedger:
    return _FakeLedger(conn)


@pytest.fixture()
def monitor(ledger: _FakeLedger) -> ContextMonitor:
    return ContextMonitor(ledger)


def _fetch_all(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return list(
        conn.execute(
            "SELECT session_id, turn_id, input_tokens, cumulative_tokens,"
            " model_max_context, headroom_ratio FROM context_window_observations"
            " ORDER BY id"
        )
    )


# ---------------------------------------------------------------------------
# observe() — happy path
# ---------------------------------------------------------------------------


def test_observe_writes_single_row(monitor: ContextMonitor, conn: sqlite3.Connection) -> None:
    monitor.observe(session_id="s1", turn_id=0, input_tokens=100, model_max_context=1000)
    rows = _fetch_all(conn)
    assert len(rows) == 1
    sid, turn, inp, cum, maxc, headroom = rows[0]
    assert sid == "s1"
    assert turn == 0
    assert inp == 100
    assert cum == 100
    assert maxc == 1000
    assert headroom == pytest.approx(0.9)


def test_observe_accumulates_across_turns(
    monitor: ContextMonitor, conn: sqlite3.Connection
) -> None:
    monitor.observe("s1", 0, 100, 1000)
    monitor.observe("s1", 1, 250, 1000)
    monitor.observe("s1", 2, 50, 1000)
    rows = _fetch_all(conn)
    assert [r[3] for r in rows] == [100, 350, 400]
    assert rows[-1][5] == pytest.approx(0.6)


def test_observe_isolates_sessions(
    monitor: ContextMonitor, conn: sqlite3.Connection
) -> None:
    monitor.observe("s1", 0, 100, 1000)
    monitor.observe("s2", 0, 200, 1000)
    monitor.observe("s1", 1, 100, 1000)
    rows = _fetch_all(conn)
    s1_rows = [r for r in rows if r[0] == "s1"]
    s2_rows = [r for r in rows if r[0] == "s2"]
    assert [r[3] for r in s1_rows] == [100, 200]
    assert [r[3] for r in s2_rows] == [200]


def test_observe_coerces_session_id_to_str(
    monitor: ContextMonitor, conn: sqlite3.Connection
) -> None:
    monitor.observe(session_id=42, turn_id=0, input_tokens=10, model_max_context=100)  # type: ignore[arg-type]
    rows = _fetch_all(conn)
    assert rows[0][0] == "42"


# ---------------------------------------------------------------------------
# Headroom clamping — confidence-threshold analogue
# ---------------------------------------------------------------------------


def test_headroom_clamped_at_zero_when_overflowing(
    monitor: ContextMonitor, conn: sqlite3.Connection
) -> None:
    # Cumulative tokens exceed max context — headroom must clamp to 0.0.
    monitor.observe("s1", 0, 800, 1000)
    monitor.observe("s1", 1, 500, 1000)  # cumulative=1300 > 1000
    rows = _fetch_all(conn)
    assert rows[-1][5] == 0.0


def test_headroom_clamped_at_one_when_zero_input(
    monitor: ContextMonitor, conn: sqlite3.Connection
) -> None:
    monitor.observe("s1", 0, 0, 1000)
    rows = _fetch_all(conn)
    assert rows[0][5] == 1.0


def test_headroom_exact_boundary_at_full(
    monitor: ContextMonitor, conn: sqlite3.Connection
) -> None:
    monitor.observe("s1", 0, 1000, 1000)
    rows = _fetch_all(conn)
    assert rows[0][5] == 0.0


# ---------------------------------------------------------------------------
# Validation — edge cases
# ---------------------------------------------------------------------------


def test_negative_input_tokens_raises(monitor: ContextMonitor) -> None:
    with pytest.raises(ValueError, match="input_tokens"):
        monitor.observe("s1", 0, -1, 1000)


def test_zero_max_context_raises(monitor: ContextMonitor) -> None:
    with pytest.raises(ValueError, match="model_max_context"):
        monitor.observe("s1", 0, 100, 0)


def test_negative_max_context_raises(monitor: ContextMonitor) -> None:
    with pytest.raises(ValueError, match="model_max_context"):
        monitor.observe("s1", 0, 100, -10)


def test_negative_turn_id_raises(monitor: ContextMonitor) -> None:
    with pytest.raises(ValueError, match="turn_id"):
        monitor.observe("s1", -1, 100, 1000)


def test_validation_failure_does_not_write(
    monitor: ContextMonitor, conn: sqlite3.Connection
) -> None:
    with pytest.raises(ValueError):
        monitor.observe("s1", 0, -1, 1000)
    assert _fetch_all(conn) == []


def test_validation_failure_does_not_increment_cumulative(
    monitor: ContextMonitor, conn: sqlite3.Connection
) -> None:
    monitor.observe("s1", 0, 100, 1000)
    with pytest.raises(ValueError):
        monitor.observe("s1", 1, -5, 1000)
    monitor.observe("s1", 2, 50, 1000)
    rows = _fetch_all(conn)
    assert [r[3] for r in rows] == [100, 150]


# ---------------------------------------------------------------------------
# reset_session()
# ---------------------------------------------------------------------------


def test_reset_session_clears_in_memory_counter(
    monitor: ContextMonitor, conn: sqlite3.Connection
) -> None:
    monitor.observe("s1", 0, 300, 1000)
    monitor.reset_session("s1")
    monitor.observe("s1", 1, 50, 1000)
    rows = _fetch_all(conn)
    assert rows[-1][3] == 50  # cumulative restarted
    assert rows[-1][5] == pytest.approx(0.95)


def test_reset_session_does_not_delete_ledger_rows(
    monitor: ContextMonitor, conn: sqlite3.Connection
) -> None:
    monitor.observe("s1", 0, 300, 1000)
    monitor.observe("s1", 1, 200, 1000)
    monitor.reset_session("s1")
    rows = _fetch_all(conn)
    assert len(rows) == 2  # audit trail preserved


def test_reset_session_unknown_id_is_noop(monitor: ContextMonitor) -> None:
    monitor.reset_session("never-seen")  # must not raise


def test_reset_session_isolated(
    monitor: ContextMonitor, conn: sqlite3.Connection
) -> None:
    monitor.observe("s1", 0, 100, 1000)
    monitor.observe("s2", 0, 200, 1000)
    monitor.reset_session("s1")
    monitor.observe("s2", 1, 100, 1000)
    rows = _fetch_all(conn)
    s2_rows = [r for r in rows if r[0] == "s2"]
    assert s2_rows[-1][3] == 300  # s2 untouched by s1 reset


# ---------------------------------------------------------------------------
# Error handling — backend failure
# ---------------------------------------------------------------------------


def test_backend_execute_failure_propagates() -> None:
    fake_conn = MagicMock(spec=sqlite3.Connection)
    fake_conn.execute.side_effect = sqlite3.OperationalError("disk I/O error")
    monitor = ContextMonitor(_FakeLedger(fake_conn))
    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        monitor.observe("s1", 0, 100, 1000)


def test_observed_at_is_iso8601_utc(
    monitor: ContextMonitor, conn: sqlite3.Connection
) -> None:
    monitor.observe("s1", 0, 100, 1000)
    (observed_at,) = conn.execute(
        "SELECT observed_at FROM context_window_observations"
    ).fetchone()
    assert observed_at.endswith("Z")
    assert "T" in observed_at


def test_commit_called_after_insert() -> None:
    fake_conn = MagicMock(spec=sqlite3.Connection)
    monitor = ContextMonitor(_FakeLedger(fake_conn))
    monitor.observe("s1", 0, 100, 1000)
    fake_conn.execute.assert_called_once()
    fake_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Numeric coercion
# ---------------------------------------------------------------------------


def test_float_tokens_coerced_to_int(
    monitor: ContextMonitor, conn: sqlite3.Connection
) -> None:
    monitor.observe("s1", 0, 100.7, 1000)  # type: ignore[arg-type]
    rows = _fetch_all(conn)
    assert rows[0][2] == 100
    assert rows[0][3] == 100
