# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""A CEC claim only counts once its revisit horizon has actually elapsed.

``add_prediction`` has always stored ``horizon_days``, but nothing read it:
``_paired_observations`` joined predictions to outcomes with no maturity
filter, so a claim asserted with a 30-day horizon and marked "held up" the
same afternoon contributed to the reliability curve immediately. That made
the forward-looking part of the meta-calibration declarative — the number was
computed over claims that had not yet had the chance to be wrong.

These tests pin the maturity filter and the injectable clock it needs.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from lub.challenge.meta_calibration import MetaCalibrator

# Mirrors the real ledger schema (src/lub/ledger/schema.py:93-105), including
# the created_at / recorded_at columns the maturity filter depends on.
_SCHEMA = """
CREATE TABLE cec_meta_predictions (
    claim_id             TEXT PRIMARY KEY,
    predicted_confidence REAL NOT NULL,
    horizon_days         INTEGER NOT NULL,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE cec_meta_outcomes (
    claim_id     TEXT PRIMARY KEY,
    held_up      INTEGER NOT NULL CHECK (held_up IN (0, 1)),
    recorded_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY(claim_id) REFERENCES cec_meta_predictions(claim_id)
);
"""

NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)


class _StubLedger:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn


@pytest.fixture()
def conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    yield c
    c.close()


@pytest.fixture()
def calibrator(conn: sqlite3.Connection) -> MetaCalibrator:
    return MetaCalibrator(_StubLedger(conn), n_bins=10)


def _claim(
    conn: sqlite3.Connection,
    claim_id: str,
    *,
    confidence: float,
    horizon_days: int,
    created_at: datetime,
    held_up: bool,
) -> None:
    """Insert a prediction with an explicit creation time plus its outcome."""
    # Same shape the ledger writes: SQLite's %f is SS.SSS, so seconds are
    # explicit here and microseconds are truncated to milliseconds.
    stamp = created_at.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    conn.execute(
        "INSERT INTO cec_meta_predictions"
        " (claim_id, predicted_confidence, horizon_days, created_at) VALUES (?, ?, ?, ?)",
        (claim_id, confidence, horizon_days, stamp),
    )
    conn.execute(
        "INSERT INTO cec_meta_outcomes (claim_id, held_up) VALUES (?, ?)",
        (claim_id, int(held_up)),
    )
    conn.commit()


# --- the maturity filter ----------------------------------------------------


def test_immature_claim_is_excluded_from_the_curve(
    conn: sqlite3.Connection, calibrator: MetaCalibrator
) -> None:
    """A 30-day claim marked today has not had its chance to be wrong yet."""
    _claim(
        conn,
        "c-immature",
        confidence=0.9,
        horizon_days=30,
        created_at=NOW - timedelta(days=1),
        held_up=True,
    )

    assert calibrator._paired_observations(now=NOW) == []


def test_matured_claim_is_included(conn: sqlite3.Connection, calibrator: MetaCalibrator) -> None:
    _claim(
        conn,
        "c-mature",
        confidence=0.8,
        horizon_days=7,
        created_at=NOW - timedelta(days=8),
        held_up=True,
    )

    assert calibrator._paired_observations(now=NOW) == [(0.8, 1)]


def test_zero_horizon_claim_counts_immediately(
    conn: sqlite3.Connection, calibrator: MetaCalibrator
) -> None:
    """horizon_days=0 means 'no waiting period', not 'never mature'."""
    _claim(
        conn,
        "c-now",
        confidence=0.5,
        horizon_days=0,
        created_at=NOW,
        held_up=False,
    )

    assert calibrator._paired_observations(now=NOW) == [(0.5, 0)]


def test_the_same_claim_matures_as_the_clock_advances(
    conn: sqlite3.Connection, calibrator: MetaCalibrator
) -> None:
    """Proves the injected clock is honoured — no sleeping in tests."""
    _claim(
        conn,
        "c-ripening",
        confidence=0.7,
        horizon_days=30,
        created_at=NOW,
        held_up=True,
    )

    assert calibrator._paired_observations(now=NOW) == []
    assert calibrator._paired_observations(now=NOW + timedelta(days=31)) == [(0.7, 1)]


def test_reliability_curve_ignores_immature_claims(
    conn: sqlite3.Connection, calibrator: MetaCalibrator
) -> None:
    """The public entry point must inherit the filter, not just the reader."""
    _claim(
        conn,
        "c-young",
        confidence=0.95,
        horizon_days=90,
        created_at=NOW,
        held_up=True,
    )

    curve = calibrator.reliability_curve(now=NOW)

    assert sum(n for _, _, n in curve.bins) == 0
    assert curve.ece == 0.0


# --- the visible counterpart ------------------------------------------------


def test_pending_claims_counts_what_the_filter_held_back(
    conn: sqlite3.Connection, calibrator: MetaCalibrator
) -> None:
    _claim(
        conn,
        "c-mature",
        confidence=0.8,
        horizon_days=1,
        created_at=NOW - timedelta(days=5),
        held_up=True,
    )
    _claim(
        conn,
        "c-immature",
        confidence=0.6,
        horizon_days=60,
        created_at=NOW,
        held_up=True,
    )

    assert calibrator.pending_claims(now=NOW) == 1
    assert len(calibrator._paired_observations(now=NOW)) == 1


def test_pending_claims_is_zero_when_everything_matured(
    conn: sqlite3.Connection, calibrator: MetaCalibrator
) -> None:
    _claim(
        conn,
        "c-old",
        confidence=0.4,
        horizon_days=1,
        created_at=NOW - timedelta(days=400),
        held_up=False,
    )

    assert calibrator.pending_claims(now=NOW) == 0
