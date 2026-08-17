# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Integration tests for the two Context Autopilot MCP tools.

Hermetic — no LLM calls, no network. Each tool is invoked through its
public ``ToolDef.handler`` so the schema validation path is exercised.

Spec: planning/25_Context_Autopilot_Spec_2026-04-25.md section 1.4.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lub.challenge.context_autopilot import ContextMonitor
from lub.ledger import Ledger
from lub.mcp.tools import (
    build_auto_tools,
    build_context_autopilot_tools,
)


def _seed_ledger(tmp_path: Path, session_id: str = "sess-1") -> Path:
    db_path = tmp_path / "ca_test.db"
    led = Ledger(str(db_path))
    mon = ContextMonitor(ledger=led)
    for i in range(5):
        mon.observe(session_id, i, 200 + i * 100, 4000)
    led.close()
    return db_path


def test_build_context_autopilot_tools_returns_two() -> None:
    tools = build_context_autopilot_tools()
    names = {t.name for t in tools}
    assert names == {
        "lub.challenge.context_autopilot.observe",
        "lub.challenge.context_autopilot.simulate_ejection",
    }


def test_context_autopilot_tools_in_auto_catalog() -> None:
    auto = build_auto_tools()
    names = {t.name for t in auto}
    assert "lub.challenge.context_autopilot.observe" in names
    assert "lub.challenge.context_autopilot.simulate_ejection" in names


def test_observe_tool_returns_summary(tmp_path: Path) -> None:
    db_path = _seed_ledger(tmp_path)
    tool = next(
        t
        for t in build_context_autopilot_tools()
        if t.name == "lub.challenge.context_autopilot.observe"
    )
    out = tool.handler(
        {
            "session_id": "sess-1",
            "ledger_path": str(db_path),
        }
    )
    assert out["session_id"] == "sess-1"
    assert out["n_turns"] == 5
    # 200 + 300 + 400 + 500 + 600 = 2000
    assert out["total_input_tokens"] == 2000
    assert out["peak_cumulative_tokens"] == 2000
    assert out["model_max_context"] == 4000
    assert 0.0 <= out["final_headroom_ratio"] <= 1.0


def test_observe_tool_unknown_session(tmp_path: Path) -> None:
    db_path = _seed_ledger(tmp_path)
    tool = next(
        t
        for t in build_context_autopilot_tools()
        if t.name == "lub.challenge.context_autopilot.observe"
    )
    out = tool.handler(
        {"session_id": "ghost", "ledger_path": str(db_path)}
    )
    assert out["n_turns"] == 0


def test_observe_tool_rejects_extra_fields(tmp_path: Path) -> None:
    db_path = _seed_ledger(tmp_path)
    tool = next(
        t
        for t in build_context_autopilot_tools()
        if t.name == "lub.challenge.context_autopilot.observe"
    )
    with pytest.raises(Exception):
        tool.handler(
            {
                "session_id": "sess-1",
                "ledger_path": str(db_path),
                "secret_extra": "boom",
            }
        )


def test_simulate_ejection_tool_no_turns(tmp_path: Path) -> None:
    db_path = _seed_ledger(tmp_path)
    tool = next(
        t
        for t in build_context_autopilot_tools()
        if t.name == "lub.challenge.context_autopilot.simulate_ejection"
    )
    out = tool.handler(
        {
            "session_id": "sess-1",
            "threshold": 0.2,
            "ledger_path": str(db_path),
            "current_query": "anything",
        }
    )
    assert out["session_id"] == "sess-1"
    assert out["n_candidates"] == 0
    assert out["n_ejected"] == 0


def test_simulate_ejection_tool_with_turns(tmp_path: Path) -> None:
    db_path = _seed_ledger(tmp_path)
    tool = next(
        t
        for t in build_context_autopilot_tools()
        if t.name == "lub.challenge.context_autopilot.simulate_ejection"
    )
    payload = {
        "session_id": "sess-1",
        "threshold": 0.0,
        "ledger_path": str(db_path),
        "current_query": "current focus",
        "k": 2,
        "turns": [
            {"turn_id": 0, "text": "ancient kyc rule details", "age_in_turns": 10},
            {"turn_id": 1, "text": "another aml threshold", "age_in_turns": 8},
            {"turn_id": 2, "text": "current focus area discussion", "age_in_turns": 0},
        ],
    }
    out = tool.handler(payload)
    assert out["n_candidates"] == 3
    assert 0 <= out["n_ejected"] <= 2
    assert all(
        "score" in row and "similarity_term" in row for row in out["score_breakdown"]
    )
    # Counterfactual must NOT persist: the ledger has no ejection rows.
    with Ledger(str(db_path)) as led:
        rows = led._conn.execute(  # noqa: SLF001
            "SELECT id FROM context_ejections WHERE session_id='sess-1'"
        ).fetchall()
    assert rows == []


def test_simulate_ejection_threshold_validation(tmp_path: Path) -> None:
    db_path = _seed_ledger(tmp_path)
    tool = next(
        t
        for t in build_context_autopilot_tools()
        if t.name == "lub.challenge.context_autopilot.simulate_ejection"
    )
    with pytest.raises(Exception):
        tool.handler(
            {
                "session_id": "sess-1",
                "threshold": -1.0,
                "ledger_path": str(db_path),
            }
        )
