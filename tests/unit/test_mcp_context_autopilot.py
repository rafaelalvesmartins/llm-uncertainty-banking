# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the auto-wrapped MCP tools in :mod:`lub.mcp.tools.context_autopilot`.

The handlers delegate to :mod:`lub.challenge.context_autopilot`; here we
mock those collaborators so the test is hermetic and only exercises the
MCP surface (Pydantic IO schemas, payload coercion, and output mapping).

Pattern mirrors :mod:`tests.unit.test_mcp_challenge`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from lub.mcp.tools import context_autopilot as ca

# ---------------------------------------------------------------------------
# Pydantic IO schemas
# ---------------------------------------------------------------------------


def test_observe_input_requires_session_id() -> None:
    with pytest.raises(ValueError):
        ca.ObserveInput.model_validate({})


def test_observe_input_defaults_ledger_to_memory() -> None:
    parsed = ca.ObserveInput.model_validate({"session_id": "S1"})
    assert parsed.session_id == "S1"
    assert parsed.ledger_path == ":memory:"


def test_observe_input_forbids_extra_fields() -> None:
    with pytest.raises(ValueError):
        ca.ObserveInput.model_validate({"session_id": "S1", "unknown": True})


def test_simulate_ejection_input_requires_session_and_threshold() -> None:
    with pytest.raises(ValueError):
        ca.SimulateEjectionInput.model_validate({"session_id": "S1"})
    with pytest.raises(ValueError):
        ca.SimulateEjectionInput.model_validate({"threshold": 0.5})


def test_simulate_ejection_input_defaults() -> None:
    parsed = ca.SimulateEjectionInput.model_validate(
        {"session_id": "S1", "threshold": 0.7}
    )
    assert parsed.ledger_path == ":memory:"
    assert parsed.k == 10
    assert parsed.alpha == pytest.approx(0.5)
    assert parsed.beta == pytest.approx(0.2)
    assert parsed.gamma == pytest.approx(0.3)
    assert parsed.current_query == ""
    assert parsed.turns == []


def test_simulate_ejection_input_clamps_threshold_bounds() -> None:
    with pytest.raises(ValueError):
        ca.SimulateEjectionInput.model_validate(
            {"session_id": "S1", "threshold": -0.1}
        )
    with pytest.raises(ValueError):
        ca.SimulateEjectionInput.model_validate(
            {"session_id": "S1", "threshold": 10.1}
        )


def test_simulate_ejection_input_clamps_k_bounds() -> None:
    with pytest.raises(ValueError):
        ca.SimulateEjectionInput.model_validate(
            {"session_id": "S1", "threshold": 0.5, "k": 0}
        )
    with pytest.raises(ValueError):
        ca.SimulateEjectionInput.model_validate(
            {"session_id": "S1", "threshold": 0.5, "k": 1001}
        )


def test_simulate_ejection_input_forbids_extra_fields() -> None:
    with pytest.raises(ValueError):
        ca.SimulateEjectionInput.model_validate(
            {"session_id": "S1", "threshold": 0.5, "rogue": 1}
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeLedgerCM:
    """Context-manager mock that returns itself as the ledger handle."""

    def __init__(self) -> None:
        self.closed = False

    def __enter__(self) -> _FakeLedgerCM:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.closed = True


@pytest.fixture
def fake_ledger() -> _FakeLedgerCM:
    return _FakeLedgerCM()


def _fake_report(session_id: str = "S1", n: int = 2) -> SimpleNamespace:
    return SimpleNamespace(
        session_id=session_id,
        n_turns=n,
        total_input_tokens=300,
        peak_cumulative_tokens=500,
        final_cumulative_tokens=500,
        model_max_context=1000,
        min_headroom_ratio=0.4,
        max_headroom_ratio=0.9,
        final_headroom_ratio=0.5,
        observations=[
            {"turn_id": 0, "input_tokens": 100, "cumulative_tokens": 100},
            {"turn_id": 1, "input_tokens": 200, "cumulative_tokens": 300},
        ],
    )


def _fake_ejected(turn_id: int = 7) -> SimpleNamespace:
    score = SimpleNamespace(
        score=0.81,
        similarity_term=0.10,
        age_term=0.30,
        usefulness_term=0.41,
        similarity=0.20,
        age_normalised=1.5,
        historical_usefulness=0.6,
    )
    return SimpleNamespace(turn_id=turn_id, score=score)


# ---------------------------------------------------------------------------
# _handle_observe
# ---------------------------------------------------------------------------


def test_handle_observe_maps_report_fields(fake_ledger: _FakeLedgerCM) -> None:
    rep = _fake_report("S1", n=2)
    with (
        patch("lub.ledger.Ledger", return_value=fake_ledger),
        patch(
            "lub.challenge.context_autopilot.reports.load_context_window_report",
            return_value=rep,
        ) as m,
    ):
        out = ca._handle_observe({"session_id": "S1"})

    assert out["session_id"] == "S1"
    assert out["n_turns"] == 2
    assert out["total_input_tokens"] == 300
    assert out["peak_cumulative_tokens"] == 500
    assert out["final_cumulative_tokens"] == 500
    assert out["model_max_context"] == 1000
    assert out["min_headroom_ratio"] == pytest.approx(0.4)
    assert out["max_headroom_ratio"] == pytest.approx(0.9)
    assert out["final_headroom_ratio"] == pytest.approx(0.5)
    assert len(out["observations"]) == 2
    # Loader was called with the session id parsed from the payload.
    assert m.call_args.args[1] == "S1"
    # Ledger context manager was exited.
    assert fake_ledger.closed is True


def test_handle_observe_passes_ledger_path(fake_ledger: _FakeLedgerCM) -> None:
    rep = _fake_report("S2", n=0)
    with (
        patch("lub.ledger.Ledger", return_value=fake_ledger) as ledger_cls,
        patch(
            "lub.challenge.context_autopilot.reports.load_context_window_report",
            return_value=rep,
        ),
    ):
        ca._handle_observe({"session_id": "S2", "ledger_path": "/tmp/x.sqlite"})

    assert ledger_cls.call_args.args[0] == "/tmp/x.sqlite"


# ---------------------------------------------------------------------------
# _handle_simulate_ejection
# ---------------------------------------------------------------------------


def test_handle_simulate_ejection_maps_breakdown(
    fake_ledger: _FakeLedgerCM,
) -> None:
    e = _fake_ejected(turn_id=7)

    with (
        patch("lub.ledger.Ledger", return_value=fake_ledger),
        patch("lub.evidence.EvidenceStore"),
        patch(
            "lub.challenge.context_autopilot.eject_top_k", return_value=[e]
        ) as m,
    ):
        out = ca._handle_simulate_ejection(
            {
                "session_id": "S1",
                "threshold": 0.5,
                "current_query": "what now?",
                "turns": [
                    {"turn_id": 7, "text": "old turn", "age_in_turns": 3},
                ],
            }
        )

    assert out["session_id"] == "S1"
    assert out["threshold"] == pytest.approx(0.5)
    assert out["n_candidates"] == 1
    assert out["n_ejected"] == 1
    assert out["ejected_turn_ids"] == [7]
    assert len(out["score_breakdown"]) == 1
    sb = out["score_breakdown"][0]
    assert sb["turn_id"] == 7
    assert sb["score"] == pytest.approx(0.81)
    assert sb["similarity_term"] == pytest.approx(0.10)
    assert sb["age_term"] == pytest.approx(0.30)
    assert sb["usefulness_term"] == pytest.approx(0.41)
    assert sb["similarity"] == pytest.approx(0.20)
    assert sb["age_normalised"] == pytest.approx(1.5)
    assert sb["historical_usefulness"] == pytest.approx(0.6)
    # Metadata reflects the inputs and forces persist=False (read-only).
    assert out["metadata"]["alpha"] == pytest.approx(0.5)
    assert out["metadata"]["beta"] == pytest.approx(0.2)
    assert out["metadata"]["gamma"] == pytest.approx(0.3)
    assert out["metadata"]["k"] == 10
    assert out["metadata"]["persist"] is False
    # eject_top_k must be called with persist=False.
    assert m.call_args.kwargs["persist"] is False
    assert m.call_args.kwargs["session_id"] == "S1"
    assert m.call_args.kwargs["threshold"] == pytest.approx(0.5)
    assert fake_ledger.closed is True


def test_handle_simulate_ejection_empty_turns(
    fake_ledger: _FakeLedgerCM,
) -> None:
    with (
        patch("lub.ledger.Ledger", return_value=fake_ledger),
        patch("lub.evidence.EvidenceStore"),
        patch(
            "lub.challenge.context_autopilot.eject_top_k", return_value=[]
        ) as m,
    ):
        out = ca._handle_simulate_ejection(
            {"session_id": "S1", "threshold": 0.5}
        )

    assert out["n_candidates"] == 0
    assert out["n_ejected"] == 0
    assert out["ejected_turn_ids"] == []
    assert out["score_breakdown"] == []
    # No turns were supplied so the engine receives an empty list.
    assert m.call_args.args[0] == []


def test_handle_simulate_ejection_coerces_turn_fields(
    fake_ledger: _FakeLedgerCM,
) -> None:
    """Turn dicts use ``get(...)`` defaults and int/str coercion."""
    with (
        patch("lub.ledger.Ledger", return_value=fake_ledger),
        patch("lub.evidence.EvidenceStore"),
        patch(
            "lub.challenge.context_autopilot.eject_top_k", return_value=[]
        ) as m,
    ):
        ca._handle_simulate_ejection(
            {
                "session_id": "S1",
                "threshold": 0.5,
                "turns": [
                    {},  # missing everything -> defaults to index/empty/0
                    {"turn_id": "42", "text": "hi", "age_in_turns": "3"},
                ],
            }
        )

    turns_arg = m.call_args.args[0]
    assert len(turns_arg) == 2
    # First turn defaults: turn_id falls back to enumerate index (0).
    assert turns_arg[0].turn_id == 0
    assert turns_arg[0].text == ""
    assert turns_arg[0].age_in_turns == 0
    # Second turn: string ids/ages are coerced to int.
    assert turns_arg[1].turn_id == 42
    assert turns_arg[1].text == "hi"
    assert turns_arg[1].age_in_turns == 3


# ---------------------------------------------------------------------------
# build_context_autopilot_tools
# ---------------------------------------------------------------------------


def test_build_tools_registers_two_tools() -> None:
    tools = ca.build_context_autopilot_tools()
    assert len(tools) == 2
    names = [t.name for t in tools]
    assert names == [
        "lub.challenge.context_autopilot.observe",
        "lub.challenge.context_autopilot.simulate_ejection",
    ]


def test_build_tools_wires_correct_schemas() -> None:
    tools = {t.name: t for t in ca.build_context_autopilot_tools()}
    obs = tools["lub.challenge.context_autopilot.observe"]
    sim = tools["lub.challenge.context_autopilot.simulate_ejection"]
    assert obs.input_model is ca.ObserveInput
    assert obs.output_model is ca.ObserveOutput
    assert sim.input_model is ca.SimulateEjectionInput
    assert sim.output_model is ca.SimulateEjectionOutput


def test_build_tools_handlers_are_callable() -> None:
    for t in ca.build_context_autopilot_tools():
        assert callable(t.handler)
        assert t.description  # non-empty description
