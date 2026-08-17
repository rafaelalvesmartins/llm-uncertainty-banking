# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

from pathlib import Path

import pytest

from lub.ledger import Ledger


def test_schema_created_in_memory() -> None:
    led = Ledger(":memory:")
    tables = {
        r[0]
        for r in led._conn.execute(  # noqa: SLF001
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for expected in ("queries", "answers", "uq_scores", "outcomes", "policy_decisions"):
        assert expected in tables
    led.close()


def test_log_and_fetch_round_trip() -> None:
    with Ledger(":memory:") as led:
        qid = led.log_query(prompt="hello", domain="regulatory-qa")
        aid = led.log_answer(qid, model="dummy", backend="dummy", answer="world", cost=0.01)
        led.log_score(aid, method="p_true", value=0.8)
        led.log_score(aid, method="confidence", value=0.85)
        led.log_policy(aid, decision="PASSTHROUGH", threshold=0.5, passed=True, reason="ok")
        led.update_outcome(aid, correct=True, ground_truth="world")

        ans = led.fetch_answer(aid)
        assert ans is not None
        assert ans["answer"] == "world"
        assert ans["cost"] == pytest.approx(0.01)
        scores = {s["method"]: s["value"] for s in led.fetch_scores(aid)}
        assert scores["p_true"] == pytest.approx(0.8)


def test_replay_calibration_produces_n_buckets() -> None:
    with Ledger(":memory:") as led:
        for i in range(20):
            qid = led.log_query(prompt=f"q{i}")
            aid = led.log_answer(qid, model="m", backend="b", answer=f"a{i}")
            led.log_score(aid, method="confidence", value=(i % 10) / 10.0 + 0.05)
            led.update_outcome(aid, correct=(i % 2 == 0))
        points = led.replay_calibration(method="confidence", n_buckets=5)
        assert len(points) == 5
        total_n = sum(p.n for p in points)
        assert total_n == 20


def test_replay_calibration_rejects_zero_buckets() -> None:
    with Ledger(":memory:") as led, pytest.raises(ValueError, match="positive"):
        led.replay_calibration(n_buckets=0)


def test_prompt_hash_is_deterministic() -> None:
    a = Ledger._hash_prompt("hello")
    b = Ledger._hash_prompt("hello")
    c = Ledger._hash_prompt("world")
    assert a == b
    assert a != c


def test_schema_version_refreshed_on_reopen(tmp_path: Path) -> None:
    """Reopening an old-version file must stamp the current schema version.

    The SCHEMA_SQL migrations are additive (CREATE TABLE IF NOT EXISTS),
    so opening an old file upgrades it in place; ``_ledger_meta`` must
    report the version the file now has, not the one it was born with.
    """
    from lub.ledger.schema import SCHEMA_VERSION

    db = tmp_path / "ledger.db"
    led = Ledger(db)
    led._conn.execute(  # noqa: SLF001
        "UPDATE _ledger_meta SET value = '1' WHERE key = 'schema_version'"
    )
    led._conn.commit()  # noqa: SLF001
    led.close()

    led2 = Ledger(db)
    try:
        row = led2._conn.execute(  # noqa: SLF001
            "SELECT value FROM _ledger_meta WHERE key = 'schema_version'"
        ).fetchone()
        assert row["value"] == str(SCHEMA_VERSION)
    finally:
        led2.close()
