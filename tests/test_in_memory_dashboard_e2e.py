# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""End-to-end pytest: InMemoryLedger -> dashboard, no sqlite.

Connects pass 38 (InMemoryLedger) and pass 33 (SnapshotSource) via the
pass-39 bridge (InMemorySnapshotSource). The whole dashboard rendering
stack becomes unit-testable in pure Python without filesystem or sqlite.

Spec: planning/31_Storage_Genericity_Spec_2026-04-25.md follow-on.
"""

from __future__ import annotations

from datetime import datetime

import pytest


def test_in_memory_snapshot_source_satisfies_protocol():
    from lub.dashboard.in_memory_source import InMemorySnapshotSource
    from lub.dashboard.protocols import SnapshotSource
    from lub.ledger.protocol import InMemoryLedger

    src = InMemorySnapshotSource(InMemoryLedger())
    assert isinstance(src, SnapshotSource)


def test_bridge_rejects_non_ledger_input():
    from lub.dashboard.in_memory_source import InMemorySnapshotSource
    with pytest.raises(TypeError):
        InMemorySnapshotSource(object())


def test_end_to_end_in_memory_ledger_to_html():
    """Full stack: log decisions -> bridge -> snapshot -> HTML."""
    from lub.dashboard import build_snapshot, render_html
    from lub.dashboard.in_memory_source import InMemorySnapshotSource
    from lub.ledger.protocol import InMemoryLedger

    led = InMemoryLedger()
    qid = led.log_query("Is X true?", domain="banking")
    a1 = led.log_answer(qid, "gpt-4o", "openai", "yes", tier="prime")
    a2 = led.log_answer(qid, "gpt-4o", "openai", "unsure", tier="prime")
    a3 = led.log_answer(qid, "claude-opus", "anthropic", "no", tier="strong")
    led.log_policy(a1, "EMIT", 0.7, True, "above")
    led.log_policy(a2, "REFUSE", 0.7, False, "below")
    led.log_policy(a3, "EMIT", 0.7, True, "ok")
    led.update_outcome(a1, correct=True)
    led.update_outcome(a3, correct=True)

    src = InMemorySnapshotSource(led)
    snap = build_snapshot(
        src, evidence_store=None,
        period_start=datetime(2020, 1, 1), period_end=datetime(2030, 1, 1),
        tenant="e2e", git_sha="bridge",
    )

    assert snap.decisions_in_window == 3
    assert snap.abstention_rate == pytest.approx(1 / 3)
    assert snap.n_outcomes_recorded == 2
    assert snap.correctness_rate == pytest.approx(1.0)
    assert len(snap.recent_decisions) == 3

    html = render_html(snap)
    assert html.startswith("<!DOCTYPE html>")
    assert "e2e" in html
    assert "33.3%" in html  # abstention
    assert "100.0%" in html  # correctness
    assert "claude-opus" in html  # row from recent decisions


def test_empty_in_memory_ledger_renders_empty_snapshot():
    from lub.dashboard import build_snapshot
    from lub.dashboard.in_memory_source import InMemorySnapshotSource
    from lub.ledger.protocol import InMemoryLedger

    src = InMemorySnapshotSource(InMemoryLedger())
    snap = build_snapshot(
        src, evidence_store=None,
        period_start=datetime(2020, 1, 1), period_end=datetime(2030, 1, 1),
    )
    assert snap.decisions_in_window == 0
    assert snap.correctness_rate is None
    assert snap.recent_decisions == []
