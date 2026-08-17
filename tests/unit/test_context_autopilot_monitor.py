# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Unit tests for :mod:`lub.challenge.context_autopilot.monitor`.

Spec: planning/25_Context_Autopilot_Spec_2026-04-25.md section 1.1.
"""

from __future__ import annotations

import pytest

from lub.challenge.context_autopilot import ContextMonitor
from lub.ledger import Ledger
from lub.ledger.schema import SCHEMA_VERSION


def test_schema_v3_creates_context_autopilot_tables() -> None:
    with Ledger(":memory:") as led:
        tables = {
            r[0]
            for r in led._conn.execute(  # noqa: SLF001
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "context_window_observations" in tables
    assert "context_ejections" in tables
    assert "context_recall_flags" in tables


def test_schema_version_is_at_least_3() -> None:
    assert SCHEMA_VERSION >= 3


def test_observe_writes_one_row() -> None:
    with Ledger(":memory:") as led:
        mon = ContextMonitor(ledger=led)
        mon.observe("session-A", turn_id=0, input_tokens=100, model_max_context=1000)
        rows = led._conn.execute(  # noqa: SLF001
            "SELECT session_id, turn_id, input_tokens, cumulative_tokens,"
            " model_max_context, headroom_ratio"
            " FROM context_window_observations"
        ).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r[0] == "session-A"
    assert r[1] == 0
    assert r[2] == 100
    assert r[3] == 100
    assert r[4] == 1000
    assert r[5] == pytest.approx(0.9, abs=1e-6)


def test_observe_accumulates_within_session() -> None:
    with Ledger(":memory:") as led:
        mon = ContextMonitor(ledger=led)
        mon.observe("S", 0, 100, 1000)
        mon.observe("S", 1, 200, 1000)
        mon.observe("S", 2, 50, 1000)
        rows = led._conn.execute(  # noqa: SLF001
            "SELECT cumulative_tokens, headroom_ratio FROM context_window_observations"
            " WHERE session_id='S' ORDER BY turn_id"
        ).fetchall()
    assert [r[0] for r in rows] == [100, 300, 350]
    assert rows[-1][1] == pytest.approx(1.0 - 350 / 1000, abs=1e-6)


def test_observe_separates_sessions() -> None:
    with Ledger(":memory:") as led:
        mon = ContextMonitor(ledger=led)
        mon.observe("a", 0, 50, 1000)
        mon.observe("b", 0, 200, 1000)
        a_total = led._conn.execute(  # noqa: SLF001
            "SELECT cumulative_tokens FROM context_window_observations"
            " WHERE session_id='a' ORDER BY turn_id DESC LIMIT 1"
        ).fetchone()[0]
        b_total = led._conn.execute(  # noqa: SLF001
            "SELECT cumulative_tokens FROM context_window_observations"
            " WHERE session_id='b' ORDER BY turn_id DESC LIMIT 1"
        ).fetchone()[0]
    assert a_total == 50
    assert b_total == 200


def test_observe_clamps_headroom_to_zero_on_overflow() -> None:
    with Ledger(":memory:") as led:
        mon = ContextMonitor(ledger=led)
        mon.observe("X", 0, 1500, 1000)  # exceeds max
        row = led._conn.execute(  # noqa: SLF001
            "SELECT headroom_ratio FROM context_window_observations"
        ).fetchone()
    assert row[0] == 0.0


def test_observe_rejects_negative_input_tokens() -> None:
    with Ledger(":memory:") as led:
        mon = ContextMonitor(ledger=led)
        with pytest.raises(ValueError, match="non-negative"):
            mon.observe("S", 0, -1, 1000)


def test_observe_rejects_nonpositive_max_context() -> None:
    with Ledger(":memory:") as led:
        mon = ContextMonitor(ledger=led)
        with pytest.raises(ValueError, match="positive"):
            mon.observe("S", 0, 100, 0)


def test_observe_rejects_negative_turn_id() -> None:
    with Ledger(":memory:") as led:
        mon = ContextMonitor(ledger=led)
        with pytest.raises(ValueError, match="non-negative"):
            mon.observe("S", -1, 100, 1000)


def test_reset_session_clears_in_memory_counter() -> None:
    with Ledger(":memory:") as led:
        mon = ContextMonitor(ledger=led)
        mon.observe("Z", 0, 100, 1000)
        mon.observe("Z", 1, 100, 1000)
        mon.reset_session("Z")
        mon.observe("Z", 2, 100, 1000)
        # After reset the cumulative restarts at 100 even though the
        # ledger keeps every previous row.
        rows = led._conn.execute(  # noqa: SLF001
            "SELECT cumulative_tokens FROM context_window_observations"
            " WHERE session_id='Z' ORDER BY id"
        ).fetchall()
    assert [r[0] for r in rows] == [100, 200, 100]


def test_reset_unknown_session_is_noop() -> None:
    with Ledger(":memory:") as led:
        mon = ContextMonitor(ledger=led)
        # Should not raise.
        mon.reset_session("never-seen")


def test_observe_records_distinct_observed_at_strings() -> None:
    with Ledger(":memory:") as led:
        mon = ContextMonitor(ledger=led)
        mon.observe("S", 0, 10, 1000)
        mon.observe("S", 1, 10, 1000)
        rows = led._conn.execute(  # noqa: SLF001
            "SELECT observed_at FROM context_window_observations"
            " WHERE session_id='S'"
        ).fetchall()
    # All rows must have a non-empty timestamp; we don't assert
    # uniqueness because SQLite's strftime-now resolves to ms.
    assert all(isinstance(r[0], str) and r[0] for r in rows)
