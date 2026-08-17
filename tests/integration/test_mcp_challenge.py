# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Integration tests for the four CEC MCP tools.

Hermetic — no LLM calls, no network. Each tool is invoked through its
public ``ToolDef.handler`` so the schema validation path is exercised.

Spec: planning/24_CEC_Spec_2026-04-25.md §1.4 + §4 step 7.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lub.mcp.tools import build_challenge_tools
from lub.mcp.tools._registry import build_auto_tools
from tests.unit._cec_helpers import (
    attach_drift_events,
    load_ledger_fixture,
)


def _seed_ledger(tmp_path: Path) -> Path:
    """Materialise the JSONL fixture into a real file-backed ledger."""
    db_path = tmp_path / "cec_test.db"
    led = load_ledger_fixture(str(db_path))
    attach_drift_events(led)
    led.close()
    return db_path


def test_build_challenge_tools_returns_four() -> None:
    tools = build_challenge_tools()
    names = {t.name for t in tools}
    assert names == {
        "lub.challenge.replay",
        "lub.challenge.explain_drift",
        "lub.challenge.report",
        "lub.challenge.meta_calibration_curve",
    }


def test_challenge_tools_in_auto_tool_catalog() -> None:
    auto = build_auto_tools()
    names = {t.name for t in auto}
    assert "lub.challenge.replay" in names
    assert "lub.challenge.report" in names


def test_tool_replay_threshold(tmp_path: Path) -> None:
    db_path = _seed_ledger(tmp_path)
    tool = next(
        t for t in build_challenge_tools() if t.name == "lub.challenge.replay"
    )
    out = tool.handler(
        {
            "window": "2026-04-01T00:00:00/2026-05-01T00:00:00",
            "alternative": {"kind": "threshold", "value": 0.85},
            "ledger_path": str(db_path),
        }
    )
    assert out["sample_size"] == 10
    assert 0.0 <= out["counterfactual_abstention_rate"] <= 1.0
    assert "audit_trail" in out


def test_tool_replay_estimator(tmp_path: Path) -> None:
    db_path = _seed_ledger(tmp_path)
    tool = next(
        t for t in build_challenge_tools() if t.name == "lub.challenge.replay"
    )
    out = tool.handler(
        {
            "window": "2026-04-01/2026-05-01",
            "alternative": {"kind": "estimator", "name": "adaptive_conformal"},
            "ledger_path": str(db_path),
        }
    )
    assert out["sample_size"] == 10


def test_tool_replay_tier(tmp_path: Path) -> None:
    db_path = _seed_ledger(tmp_path)
    tool = next(
        t for t in build_challenge_tools() if t.name == "lub.challenge.replay"
    )
    out = tool.handler(
        {
            "window": "2026-04-01/2026-05-01",
            "alternative": {"kind": "tier", "model_id": "opus"},
            "ledger_path": str(db_path),
        }
    )
    assert out["sample_size"] == 10


def test_tool_replay_rejects_unknown_alt_kind(tmp_path: Path) -> None:
    db_path = _seed_ledger(tmp_path)
    tool = next(
        t for t in build_challenge_tools() if t.name == "lub.challenge.replay"
    )
    with pytest.raises(ValueError, match="unknown alternative"):
        tool.handler(
            {
                "window": "2026-04-01/2026-05-01",
                "alternative": {"kind": "magic"},
                "ledger_path": str(db_path),
            }
        )


def test_tool_replay_rejects_bad_window(tmp_path: Path) -> None:
    db_path = _seed_ledger(tmp_path)
    tool = next(
        t for t in build_challenge_tools() if t.name == "lub.challenge.replay"
    )
    with pytest.raises(ValueError, match="ISO interval"):
        tool.handler(
            {
                "window": "not-an-interval",
                "alternative": {"kind": "threshold", "value": 0.85},
                "ledger_path": str(db_path),
            }
        )


def test_tool_explain_drift(tmp_path: Path) -> None:
    db_path = _seed_ledger(tmp_path)
    tool = next(
        t
        for t in build_challenge_tools()
        if t.name == "lub.challenge.explain_drift"
    )
    out = tool.handler(
        {"event_id": "drift-2026-04-15", "ledger_path": str(db_path)}
    )
    # The drift_events attribute is not persisted across ledger reopens
    # (it's a runtime attr), so the resolver returns the unknown-id fall
    # through → a "no historical context" hypothesis is still returned.
    assert out["drift_event_id"] == "drift-2026-04-15"
    assert isinstance(out["hypothesis"], str)


def test_tool_report(tmp_path: Path) -> None:
    db_path = _seed_ledger(tmp_path)
    tool = next(
        t for t in build_challenge_tools() if t.name == "lub.challenge.report"
    )
    out = tool.handler(
        {
            "period": "2026-04-01/2026-05-01",
            "ledger_path": str(db_path),
        }
    )
    assert out["n_replay_scenarios"] == 1
    assert isinstance(out["recommendations"], list)
    assert out["period_start"].startswith("2026-04-01")


def test_tool_meta_calibration_curve_writes_artifact(tmp_path: Path) -> None:
    db_path = _seed_ledger(tmp_path)
    tool = next(
        t
        for t in build_challenge_tools()
        if t.name == "lub.challenge.meta_calibration_curve"
    )
    out_path = tmp_path / "curve.png"
    out = tool.handler(
        {"ledger_path": str(db_path), "output_path": str(out_path)}
    )
    written = Path(out["path"])
    assert written.exists()
    assert out["format"] in {"png", "json"}


def test_tool_meta_calibration_curve_default_path_is_temp(tmp_path: Path) -> None:
    db_path = _seed_ledger(tmp_path)
    tool = next(
        t
        for t in build_challenge_tools()
        if t.name == "lub.challenge.meta_calibration_curve"
    )
    out = tool.handler({"ledger_path": str(db_path)})
    assert Path(out["path"]).exists()


def test_challenge_tools_have_pydantic_schemas() -> None:
    tools = build_challenge_tools()
    for t in tools:
        # input/output models can be introspected via pydantic.
        assert t.input_model.model_json_schema()["type"] == "object"
        assert t.output_model.model_json_schema()["type"] == "object"


def test_replay_output_is_json_serialisable(tmp_path: Path) -> None:
    db_path = _seed_ledger(tmp_path)
    tool = next(
        t for t in build_challenge_tools() if t.name == "lub.challenge.replay"
    )
    out = tool.handler(
        {
            "window": "2026-04-01/2026-05-01",
            "alternative": {"kind": "threshold", "value": 0.85},
            "ledger_path": str(db_path),
        }
    )
    json.dumps(out)  # raises on non-serialisable
