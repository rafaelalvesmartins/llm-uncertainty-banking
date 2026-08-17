# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :mod:`lub.mcp.tools.context_autopilot`."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from lub.mcp.tools.context_autopilot import (
    ObserveInput,
    ObserveOutput,
    SimulateEjectionInput,
    SimulateEjectionOutput,
    _handle_observe,
    _handle_simulate_ejection,
    build_context_autopilot_tools,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_report() -> SimpleNamespace:
    """Return a stand-in ``ContextWindowReport`` with deterministic fields."""
    return SimpleNamespace(
        session_id="sess-1",
        n_turns=3,
        total_input_tokens=900,
        peak_cumulative_tokens=1200,
        final_cumulative_tokens=1100,
        model_max_context=8000,
        min_headroom_ratio=0.5,
        max_headroom_ratio=0.95,
        final_headroom_ratio=0.85,
        observations=[
            {"turn_id": 1, "input_tokens": 300},
            {"turn_id": 2, "input_tokens": 300},
            {"turn_id": 3, "input_tokens": 300},
        ],
    )


@pytest.fixture
def fake_ledger_ctx() -> MagicMock:
    """Return a MagicMock that behaves like ``Ledger`` as a context manager."""
    mock_ledger = MagicMock()
    mock_ledger.return_value.__enter__.return_value = MagicMock(name="ledger_handle")
    mock_ledger.return_value.__exit__.return_value = False
    return mock_ledger


def _make_ejected(turn_id: int, score_value: float) -> SimpleNamespace:
    """Build an object mirroring the ``EjectedTurn`` API used by the handler."""
    score = SimpleNamespace(
        score=score_value,
        similarity_term=0.1,
        age_term=0.2,
        usefulness_term=0.05,
        similarity=0.4,
        age_normalised=0.6,
        historical_usefulness=0.7,
    )
    return SimpleNamespace(turn_id=turn_id, score=score)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class TestObserveInput:
    def test_minimal_valid_payload(self) -> None:
        obj = ObserveInput.model_validate({"session_id": "abc"})
        assert obj.session_id == "abc"
        assert obj.ledger_path == ":memory:"

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ObserveInput.model_validate({"session_id": "abc", "bogus": 1})

    def test_session_id_required(self) -> None:
        with pytest.raises(ValidationError):
            ObserveInput.model_validate({})


class TestSimulateEjectionInput:
    def test_defaults(self) -> None:
        obj = SimulateEjectionInput.model_validate(
            {"session_id": "s", "threshold": 0.5}
        )
        assert obj.k == 10
        assert obj.alpha == 0.5
        assert obj.beta == 0.2
        assert obj.gamma == 0.3
        assert obj.current_query == ""
        assert obj.turns == []

    def test_threshold_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            SimulateEjectionInput.model_validate(
                {"session_id": "s", "threshold": -0.1}
            )
        with pytest.raises(ValidationError):
            SimulateEjectionInput.model_validate(
                {"session_id": "s", "threshold": 11.0}
            )

    def test_k_bounds(self) -> None:
        with pytest.raises(ValidationError):
            SimulateEjectionInput.model_validate(
                {"session_id": "s", "threshold": 0.5, "k": 0}
            )
        with pytest.raises(ValidationError):
            SimulateEjectionInput.model_validate(
                {"session_id": "s", "threshold": 0.5, "k": 1001}
            )


class TestObserveOutput:
    def test_round_trip(self, fake_report: SimpleNamespace) -> None:
        out = ObserveOutput(
            session_id=fake_report.session_id,
            n_turns=fake_report.n_turns,
            total_input_tokens=fake_report.total_input_tokens,
            peak_cumulative_tokens=fake_report.peak_cumulative_tokens,
            final_cumulative_tokens=fake_report.final_cumulative_tokens,
            model_max_context=fake_report.model_max_context,
            min_headroom_ratio=fake_report.min_headroom_ratio,
            max_headroom_ratio=fake_report.max_headroom_ratio,
            final_headroom_ratio=fake_report.final_headroom_ratio,
            observations=fake_report.observations,
        )
        dumped = out.model_dump()
        assert dumped["session_id"] == "sess-1"
        assert dumped["n_turns"] == 3
        assert dumped["observations"][0]["turn_id"] == 1


class TestSimulateEjectionOutput:
    def test_defaults_for_empty_run(self) -> None:
        out = SimulateEjectionOutput(
            session_id="s",
            threshold=0.5,
            n_candidates=0,
            n_ejected=0,
        )
        assert out.ejected_turn_ids == []
        assert out.score_breakdown == []
        assert out.metadata == {}


# ---------------------------------------------------------------------------
# _handle_observe
# ---------------------------------------------------------------------------


class TestHandleObserve:
    def test_returns_report_fields_verbatim(
        self, fake_report: SimpleNamespace
    ) -> None:
        with patch(
            "lub.challenge.context_autopilot.reports.load_context_window_report",
            return_value=fake_report,
        ) as mock_load, patch("lub.ledger.Ledger") as mock_ledger:
            mock_ledger.return_value.__enter__.return_value = MagicMock()
            mock_ledger.return_value.__exit__.return_value = False

            result = _handle_observe(
                {"session_id": "sess-1", "ledger_path": ":memory:"}
            )

        assert result["session_id"] == "sess-1"
        assert result["n_turns"] == 3
        assert result["total_input_tokens"] == 900
        assert result["peak_cumulative_tokens"] == 1200
        assert result["final_headroom_ratio"] == 0.85
        assert len(result["observations"]) == 3
        mock_load.assert_called_once()
        mock_ledger.assert_called_once_with(":memory:")

    def test_invalid_payload_raises(self) -> None:
        with pytest.raises(ValidationError):
            _handle_observe({"unexpected": "field"})

    def test_uses_explicit_ledger_path(self, fake_report: SimpleNamespace) -> None:
        with patch(
            "lub.challenge.context_autopilot.reports.load_context_window_report",
            return_value=fake_report,
        ), patch("lub.ledger.Ledger") as mock_ledger:
            mock_ledger.return_value.__enter__.return_value = MagicMock()
            mock_ledger.return_value.__exit__.return_value = False

            _handle_observe(
                {"session_id": "sess-1", "ledger_path": "/tmp/ledger.db"}
            )

        mock_ledger.assert_called_once_with("/tmp/ledger.db")


# ---------------------------------------------------------------------------
# _handle_simulate_ejection
# ---------------------------------------------------------------------------


class TestHandleSimulateEjection:
    def test_no_turns_yields_empty_report(self) -> None:
        with patch("lub.challenge.context_autopilot.eject_top_k", return_value=[]) as mock_eject, \
                patch("lub.challenge.context_autopilot.Turn") as mock_turn, \
                patch("lub.challenge.context_autopilot.EjectionReport") as mock_report_cls, \
                patch("lub.evidence.EvidenceStore"), \
                patch("lub.ledger.Ledger") as mock_ledger:
            mock_ledger.return_value.__enter__.return_value = MagicMock()
            mock_ledger.return_value.__exit__.return_value = False
            mock_report_cls.side_effect = lambda **kw: SimpleNamespace(**kw)

            result = _handle_simulate_ejection(
                {"session_id": "s", "threshold": 0.5}
            )

        assert result["session_id"] == "s"
        assert result["threshold"] == 0.5
        assert result["n_candidates"] == 0
        assert result["n_ejected"] == 0
        assert result["ejected_turn_ids"] == []
        assert result["score_breakdown"] == []
        assert result["metadata"]["alpha"] == 0.5
        assert result["metadata"]["beta"] == 0.2
        assert result["metadata"]["gamma"] == 0.3
        assert result["metadata"]["k"] == 10
        assert result["metadata"]["persist"] is False
        mock_eject.assert_called_once()
        mock_turn.assert_not_called()

    def test_with_turns_builds_breakdown(self) -> None:
        ejected = [_make_ejected(7, 0.9), _make_ejected(9, 0.8)]

        with patch(
            "lub.challenge.context_autopilot.eject_top_k", return_value=ejected
        ) as mock_eject, patch(
            "lub.challenge.context_autopilot.Turn"
        ) as mock_turn, patch(
            "lub.challenge.context_autopilot.EjectionReport"
        ) as mock_report_cls, patch(
            "lub.evidence.EvidenceStore"
        ), patch(
            "lub.ledger.Ledger"
        ) as mock_ledger:
            mock_ledger.return_value.__enter__.return_value = MagicMock()
            mock_ledger.return_value.__exit__.return_value = False
            mock_turn.side_effect = lambda **kw: SimpleNamespace(**kw)
            mock_report_cls.side_effect = lambda **kw: SimpleNamespace(**kw)

            result = _handle_simulate_ejection(
                {
                    "session_id": "s",
                    "threshold": 0.4,
                    "current_query": "what next?",
                    "turns": [
                        {"turn_id": 7, "text": "hello", "age_in_turns": 2},
                        {"turn_id": 9, "text": "world", "age_in_turns": 5},
                    ],
                    "alpha": 0.6,
                    "beta": 0.3,
                    "gamma": 0.1,
                    "k": 5,
                }
            )

        assert result["n_candidates"] == 2
        assert result["n_ejected"] == 2
        assert result["ejected_turn_ids"] == [7, 9]
        assert [b["turn_id"] for b in result["score_breakdown"]] == [7, 9]
        assert result["score_breakdown"][0]["score"] == 0.9
        assert result["score_breakdown"][0]["similarity_term"] == 0.1
        assert result["metadata"] == {
            "alpha": 0.6,
            "beta": 0.3,
            "gamma": 0.1,
            "k": 5,
            "persist": False,
        }

        call_kwargs = mock_eject.call_args.kwargs
        assert call_kwargs["k"] == 5
        assert call_kwargs["threshold"] == 0.4
        assert call_kwargs["alpha"] == 0.6
        assert call_kwargs["beta"] == 0.3
        assert call_kwargs["gamma"] == 0.1
        assert call_kwargs["session_id"] == "s"
        assert call_kwargs["persist"] is False

    def test_turn_defaults_when_fields_missing(self) -> None:
        captured: dict[str, list] = {}

        def fake_eject(turns, *args, **kwargs):  # type: ignore[no-untyped-def]
            captured["turns"] = list(turns)
            return []

        with patch(
            "lub.challenge.context_autopilot.eject_top_k", side_effect=fake_eject
        ), patch("lub.challenge.context_autopilot.Turn") as mock_turn, patch(
            "lub.challenge.context_autopilot.EjectionReport"
        ) as mock_report_cls, patch(
            "lub.evidence.EvidenceStore"
        ), patch(
            "lub.ledger.Ledger"
        ) as mock_ledger:
            mock_ledger.return_value.__enter__.return_value = MagicMock()
            mock_ledger.return_value.__exit__.return_value = False
            mock_turn.side_effect = lambda **kw: SimpleNamespace(**kw)
            mock_report_cls.side_effect = lambda **kw: SimpleNamespace(**kw)

            _handle_simulate_ejection(
                {
                    "session_id": "s",
                    "threshold": 0.5,
                    "turns": [{}, {"text": "only-text"}],
                }
            )

        built = captured["turns"]
        assert len(built) == 2
        assert built[0].turn_id == 0
        assert built[0].text == ""
        assert built[0].age_in_turns == 0
        assert built[1].turn_id == 1
        assert built[1].text == "only-text"


# ---------------------------------------------------------------------------
# build_context_autopilot_tools
# ---------------------------------------------------------------------------


class TestBuildContextAutopilotTools:
    def test_returns_two_tools_with_expected_names(self) -> None:
        tools = build_context_autopilot_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {
            "lub.challenge.context_autopilot.observe",
            "lub.challenge.context_autopilot.simulate_ejection",
        }

    def test_tools_wire_handlers_and_schemas(self) -> None:
        tools = {t.name: t for t in build_context_autopilot_tools()}

        observe = tools["lub.challenge.context_autopilot.observe"]
        assert observe.input_model is ObserveInput
        assert observe.output_model is ObserveOutput
        assert observe.handler is _handle_observe
        assert "context-window" in observe.description.lower()

        sim = tools["lub.challenge.context_autopilot.simulate_ejection"]
        assert sim.input_model is SimulateEjectionInput
        assert sim.output_model is SimulateEjectionOutput
        assert sim.handler is _handle_simulate_ejection
        assert "ejected" in sim.description.lower()
