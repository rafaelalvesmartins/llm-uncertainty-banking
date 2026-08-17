# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :mod:`lub.ledger.metrics`."""

from __future__ import annotations

import json
from pathlib import Path

from lub.ledger.metrics import (
    LedgerMetrics,
    collect_metrics,
    to_grafana_json,
    to_prometheus,
    write_prometheus_textfile,
)
from lub.ledger.store import Ledger


def _seed(path: Path) -> None:
    with Ledger(path) as led:
        for i in range(6):
            qid = led.log_query(prompt=f"q-{i}", domain="regulatory")
            aid = led.log_answer(
                query_id=qid,
                model="dummy",
                backend="dummy",
                answer=f"a-{i}",
                tier="haiku" if i % 2 == 0 else "sonnet",
                cost=0.01,
            )
            led.log_score(answer_id=aid, method="confidence", value=0.8)
            led.log_policy(
                answer_id=aid,
                decision="accept" if i > 0 else "abstain",
                threshold=0.5,
                passed=i > 0,
            )
            led.update_outcome(answer_id=aid, correct=bool(i % 2))


def test_collect_metrics_counts(tmp_path: Path) -> None:
    path = tmp_path / "lg.sqlite"
    _seed(path)
    with Ledger(path) as led:
        m = collect_metrics(led)
    assert isinstance(m, LedgerMetrics)
    assert m.n_answers == 6
    assert m.n_scored == 6
    assert m.n_outcomes == 6
    assert m.accuracy is not None
    assert 0.0 <= m.accuracy <= 1.0
    # 1 of 6 decisions was abstain.
    assert m.abstain_rate == 1 / 6
    assert m.tier_counts == {"haiku": 3, "sonnet": 3}
    assert "confidence" in m.ece_by_method


def test_prometheus_body_well_formed(tmp_path: Path) -> None:
    path = tmp_path / "lg.sqlite"
    _seed(path)
    with Ledger(path) as led:
        m = collect_metrics(led)
    body = to_prometheus(m)
    # Each metric gets HELP + TYPE + value triplet.
    assert "# HELP lub_ledger_answers_total" in body
    assert "# TYPE lub_ledger_answers_total gauge" in body
    # Tier label survives.
    assert 'tier="haiku"' in body
    # Ends with newline for textfile collector friendliness.
    assert body.endswith("\n")


def test_prometheus_escapes_labels(tmp_path: Path) -> None:
    path = tmp_path / "lg.sqlite"
    with Ledger(path) as led:
        qid = led.log_query(prompt="q", domain="regulatory")
        led.log_answer(
            query_id=qid,
            model="dummy",
            backend="dummy",
            answer="a",
            tier='weird"tier',
        )
    with Ledger(path) as led:
        m = collect_metrics(led)
    body = to_prometheus(m)
    assert 'tier="weird\\"tier"' in body


def test_grafana_json_is_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "lg.sqlite"
    _seed(path)
    with Ledger(path) as led:
        m = collect_metrics(led)
    blob = json.loads(to_grafana_json(m))
    assert isinstance(blob, list)
    assert any(s["target"] == "ledger_answers_total" for s in blob)
    for s in blob:
        assert "datapoints" in s
        for dp in s["datapoints"]:
            assert len(dp) == 2  # (value, timestamp_ms)


def test_write_prometheus_textfile_atomic(tmp_path: Path) -> None:
    path = tmp_path / "lg.sqlite"
    _seed(path)
    out = tmp_path / "node_exporter" / "lub.prom"
    with Ledger(path) as led:
        m = collect_metrics(led)
    written = write_prometheus_textfile(m, out)
    assert written == out
    assert out.exists()
    body = out.read_text(encoding="utf-8")
    assert "lub_ledger_answers_total" in body
    # No orphan .tmp siblings left over.
    assert not list(out.parent.glob("*.tmp"))
