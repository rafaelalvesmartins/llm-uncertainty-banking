# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""Tests for the pass-33 dashboard refactor: Protocols + plug-in sources.

The refactor decouples lub.dashboard from any single data source or output
format. This test file covers:

1. SnapshotSource Protocol is satisfied structurally (no inheritance).
2. SnapshotRenderer Protocol works via the renderer registry.
3. build_snapshot accepts a custom SnapshotSource AND (back-compat) a
   sqlite-backed Ledger directly.
4. LedgerSnapshotSource is a valid SnapshotSource implementation.
5. The renderer registry validates inputs and supports plug-in renderers.

Spec: planning/29_Dashboard_Spec_2026-04-25.md (post pass-33 refactor).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest


def _build_seeded_ledger(tmp_path):
    from lub.ledger import Ledger
    led = Ledger(tmp_path / "uq.db")
    qid = led.log_query("Q?", domain="banking")
    a1 = led.log_answer(qid, "gpt-4o", "openai", "y", tier="prime")
    a2 = led.log_answer(qid, "gpt-4o", "openai", "n", tier="prime")
    led.log_policy(a1, "EMIT", 0.7, True, "ok")
    led.log_policy(a2, "REFUSE", 0.7, False, "low")
    led.update_outcome(a1, correct=True)
    return led


# ---------------------------------------------------------------------------
# Protocols are defined and runtime-checkable
# ---------------------------------------------------------------------------


def test_snapshot_source_protocol_exists():
    from lub.dashboard.protocols import SnapshotSource
    # Should be a runtime-checkable Protocol.
    assert SnapshotSource is not None


def test_snapshot_renderer_protocol_exists():
    from lub.dashboard.protocols import SnapshotRenderer
    assert SnapshotRenderer is not None


# ---------------------------------------------------------------------------
# Default renderers auto-register on import
# ---------------------------------------------------------------------------


def test_default_renderers_auto_register():
    # Importing render must auto-register html + json.
    from lub.dashboard import render  # noqa: F401
    from lub.dashboard.protocols import get_renderer, list_renderers
    names = list_renderers()
    assert "html" in names
    assert "json" in names
    assert get_renderer("html").content_type == "text/html"
    assert get_renderer("json").content_type == "application/json"


# ---------------------------------------------------------------------------
# LedgerSnapshotSource: default implementation
# ---------------------------------------------------------------------------


def test_ledger_snapshot_source_satisfies_protocol(tmp_path):
    from lub.dashboard.ledger_source import LedgerSnapshotSource
    from lub.dashboard.protocols import SnapshotSource
    led = _build_seeded_ledger(tmp_path)
    try:
        src = LedgerSnapshotSource(led)
        assert isinstance(src, SnapshotSource)
    finally:
        led.close()


def test_ledger_snapshot_source_returns_kpis(tmp_path):
    from lub.dashboard.ledger_source import LedgerSnapshotSource
    led = _build_seeded_ledger(tmp_path)
    try:
        src = LedgerSnapshotSource(led)
        n, abst = src.kpi_decisions(datetime(2020, 1, 1), datetime(2030, 1, 1))
        assert n == 2
        assert abst == pytest.approx(0.5)
        n_o, corr = src.kpi_outcomes(datetime(2020, 1, 1), datetime(2030, 1, 1))
        assert n_o == 1
        assert corr == pytest.approx(1.0)
    finally:
        led.close()


def test_ledger_snapshot_source_rejects_non_ledger():
    from lub.dashboard.ledger_source import LedgerSnapshotSource
    with pytest.raises(TypeError, match="_conn"):
        LedgerSnapshotSource(object())


# ---------------------------------------------------------------------------
# build_snapshot: accepts SnapshotSource + back-compat for Ledger
# ---------------------------------------------------------------------------


def test_build_snapshot_accepts_snapshot_source_directly(tmp_path):
    from lub.dashboard.ledger_source import LedgerSnapshotSource
    from lub.dashboard.query import build_snapshot
    led = _build_seeded_ledger(tmp_path)
    try:
        src = LedgerSnapshotSource(led)
        snap = build_snapshot(
            src, evidence_store=None,
            period_start=datetime(2020, 1, 1), period_end=datetime(2030, 1, 1),
        )
        assert snap.decisions_in_window == 2
        assert snap.abstention_rate == pytest.approx(0.5)
    finally:
        led.close()


def test_build_snapshot_back_compat_with_ledger(tmp_path):
    """Legacy callers that passed a Ledger directly must still work."""
    from lub.dashboard.query import build_snapshot
    led = _build_seeded_ledger(tmp_path)
    try:
        snap = build_snapshot(
            led, evidence_store=None,
            period_start=datetime(2020, 1, 1), period_end=datetime(2030, 1, 1),
        )
        assert snap.decisions_in_window == 2  # back-compat shim worked
    finally:
        led.close()


def test_build_snapshot_with_custom_in_memory_source():
    """Plug-in pattern: a duck-typed source with no inheritance."""
    from lub.dashboard.protocols import SnapshotSource
    from lub.dashboard.query import build_snapshot

    class InMemorySource:
        def kpi_decisions(self, s, e): return (99, 0.25)
        def kpi_outcomes(self, s, e): return (50, 0.88)
        def kpi_meta_calibration_ece(self): return 0.07
        def recent_decisions(self, s, e, limit=25):
            return [{"created_at": "2026", "domain": "memory", "model": "fake",
                     "tier": "test", "decision": "EMIT", "reason": "fixture",
                     "passed": 1}]

    src = InMemorySource()
    assert isinstance(src, SnapshotSource)
    snap = build_snapshot(
        src, evidence_store=None,
        period_start=datetime(2020, 1, 1), period_end=datetime(2030, 1, 1),
        tenant="memtest",
    )
    assert snap.decisions_in_window == 99
    assert snap.abstention_rate == 0.25
    assert snap.correctness_rate == 0.88
    assert snap.meta_calibration_ece == 0.07


def test_build_snapshot_non_source_input_returns_empty():
    """Non-source, non-ledger input -> empty snapshot, no exception."""
    from lub.dashboard.query import build_snapshot
    snap = build_snapshot(
        object(), evidence_store=None,
        period_start=datetime(2020, 1, 1), period_end=datetime(2030, 1, 1),
    )
    assert snap.decisions_in_window == 0
    assert snap.recent_decisions == []


# ---------------------------------------------------------------------------
# Renderer registry
# ---------------------------------------------------------------------------


def test_register_custom_renderer_then_use_it():
    from lub.dashboard.protocols import (
        get_renderer,
        list_renderers,
        register_renderer,
        snapshot_renderer_registry_for_test,
    )

    _RENDERER_REGISTRY = snapshot_renderer_registry_for_test()
    from lub.dashboard.query import DashboardSnapshot

    saved = dict(_RENDERER_REGISTRY)
    try:
        def render_text(snap: Any) -> str:
            return f"DECISIONS={snap.decisions_in_window}"
        render_text.content_type = "text/plain"

        register_renderer("text", render_text)
        assert "text" in list_renderers()
        snap = DashboardSnapshot(
            period_start=datetime(2026, 4, 1),
            period_end=datetime(2026, 4, 30),
            tenant="t", git_sha="g",
            decisions_in_window=42,
        )
        assert get_renderer("text")(snap) == "DECISIONS=42"
    finally:
        _RENDERER_REGISTRY.clear()
        _RENDERER_REGISTRY.update(saved)


def test_register_renderer_rejects_empty_name():
    from lub.dashboard.protocols import register_renderer
    def r(s): return "x"
    r.content_type = "text/plain"
    with pytest.raises(ValueError, match="non-empty"):
        register_renderer("", r)


def test_register_renderer_rejects_non_callable():
    from lub.dashboard.protocols import register_renderer
    with pytest.raises(TypeError, match="callable"):
        register_renderer("bad", "not callable")  # type: ignore[arg-type]


def test_get_renderer_raises_keyerror_for_unknown():
    from lub.dashboard.protocols import get_renderer
    with pytest.raises(KeyError, match="nonexistent"):
        get_renderer("nonexistent")
