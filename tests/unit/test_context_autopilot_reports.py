# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Unit tests for :mod:`lub.challenge.context_autopilot.reports`.

Spec: planning/25_Context_Autopilot_Spec_2026-04-25.md section 1.4.
"""

from __future__ import annotations

import pytest

from lub.challenge.context_autopilot import (
    ContextMonitor,
    ContextWindowReport,
    EjectionReport,
    render_markdown,
)
from lub.challenge.context_autopilot.reports import (
    load_context_window_report,
)
from lub.ledger import Ledger


def test_load_context_window_report_empty_session() -> None:
    with Ledger(":memory:") as led:
        rep = load_context_window_report(led, "ghost")
    assert isinstance(rep, ContextWindowReport)
    assert rep.session_id == "ghost"
    assert rep.n_turns == 0
    assert rep.observations == []


def test_load_context_window_report_round_trip() -> None:
    with Ledger(":memory:") as led:
        mon = ContextMonitor(ledger=led)
        mon.observe("S", 0, 100, 1000)
        mon.observe("S", 1, 200, 1000)
        mon.observe("S", 2, 300, 1000)
        rep = load_context_window_report(led, "S")
    assert rep.n_turns == 3
    assert rep.total_input_tokens == 600
    assert rep.peak_cumulative_tokens == 600
    assert rep.final_cumulative_tokens == 600
    assert rep.model_max_context == 1000
    assert rep.final_headroom_ratio == pytest.approx(0.4, abs=1e-6)


def test_load_context_window_report_filters_by_session() -> None:
    with Ledger(":memory:") as led:
        mon = ContextMonitor(ledger=led)
        mon.observe("A", 0, 100, 1000)
        mon.observe("B", 0, 50, 1000)
        a = load_context_window_report(led, "A")
        b = load_context_window_report(led, "B")
    assert a.total_input_tokens == 100
    assert b.total_input_tokens == 50


def test_render_markdown_window() -> None:
    rep = ContextWindowReport(
        session_id="abc",
        n_turns=3,
        total_input_tokens=600,
        peak_cumulative_tokens=600,
        final_cumulative_tokens=600,
        model_max_context=1000,
        min_headroom_ratio=0.4,
        max_headroom_ratio=0.9,
        final_headroom_ratio=0.4,
    )
    md = render_markdown(rep)
    assert "Context Window Report" in md
    assert "abc" in md
    assert "1000" in md
    assert md.endswith("\n")


def test_render_markdown_ejection() -> None:
    rep = EjectionReport(
        session_id="z",
        threshold=0.42,
        n_candidates=5,
        n_ejected=2,
        ejected_turn_ids=[1, 3],
    )
    md = render_markdown(rep)
    assert "Ejection Report" in md
    assert "0.420" in md
    assert "1, 3" in md


def test_render_markdown_rejects_unknown_type() -> None:
    with pytest.raises(TypeError):
        render_markdown(object())  # type: ignore[arg-type]


def test_context_window_report_dataclass_defaults() -> None:
    rep = ContextWindowReport(
        session_id="s",
        n_turns=0,
        total_input_tokens=0,
        peak_cumulative_tokens=0,
        final_cumulative_tokens=0,
        model_max_context=1000,
        min_headroom_ratio=1.0,
        max_headroom_ratio=1.0,
        final_headroom_ratio=1.0,
    )
    assert rep.observations == []


def test_ejection_report_dataclass_defaults() -> None:
    rep = EjectionReport(
        session_id="s", threshold=0.0, n_candidates=0, n_ejected=0
    )
    assert rep.ejected_turn_ids == []
    assert rep.score_breakdown == []
    assert rep.metadata == {}
