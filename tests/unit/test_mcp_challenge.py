# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the auto-wrapped MCP tools in :mod:`lub.mcp.tools.challenge`.

The handlers delegate to :mod:`lub.challenge`; here we mock those
collaborators so the test is hermetic and only exercises the MCP
surface (Pydantic IO schemas, interval parsing, alternative descriptor
building, and output mapping).
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from lub.mcp.tools import challenge as ch

# ---------------------------------------------------------------------------
# Pydantic IO schemas
# ---------------------------------------------------------------------------


def test_replay_input_requires_window_and_alternative() -> None:
    with pytest.raises(ValueError):
        ch.ChallengeReplayInput.model_validate({"window": "2026-01-01/2026-02-01"})


def test_replay_input_forbids_extra_fields() -> None:
    with pytest.raises(ValueError):
        ch.ChallengeReplayInput.model_validate(
            {
                "window": "2026-01-01/2026-02-01",
                "alternative": {"kind": "threshold", "value": 0.7},
                "unknown_field": True,
            }
        )


def test_replay_input_defaults_ledger_to_memory() -> None:
    parsed = ch.ChallengeReplayInput.model_validate(
        {
            "window": "2026-01-01/2026-02-01",
            "alternative": {"kind": "threshold", "value": 0.7},
        }
    )
    assert parsed.ledger_path == ":memory:"


def test_explain_drift_input_clamps_k_within_bounds() -> None:
    with pytest.raises(ValueError):
        ch.ExplainDriftInput.model_validate({"event_id": "evt-1", "k": 0})
    with pytest.raises(ValueError):
        ch.ExplainDriftInput.model_validate({"event_id": "evt-1", "k": 100})
    parsed = ch.ExplainDriftInput.model_validate({"event_id": "evt-1", "k": 5})
    assert parsed.k == 5


def test_report_input_defaults() -> None:
    parsed = ch.ReportInput.model_validate({"period": "2026-01-01/2026-02-01"})
    assert parsed.ledger_path == ":memory:"


def test_curve_input_accepts_optional_output_path() -> None:
    parsed = ch.CurveInput.model_validate({})
    assert parsed.ledger_path == ":memory:"
    assert parsed.output_path is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_parse_interval_splits_on_slash() -> None:
    assert ch._parse_interval("2026-01-01/2026-02-01") == ("2026-01-01", "2026-02-01")


def test_parse_interval_strips_whitespace() -> None:
    assert ch._parse_interval(" 2026-01-01 / 2026-02-01 ") == (
        "2026-01-01",
        "2026-02-01",
    )


def test_parse_interval_rejects_missing_slash() -> None:
    with pytest.raises(ValueError, match="ISO interval"):
        ch._parse_interval("2026-01-01")


def test_to_datetime_handles_z_suffix() -> None:
    dt = ch._to_datetime("2026-01-01T00:00:00Z")
    assert dt == _dt.datetime(2026, 1, 1, 0, 0, 0)
    assert dt.tzinfo is None


def test_to_datetime_strips_offset() -> None:
    dt = ch._to_datetime("2026-01-01T00:00:00+03:00")
    assert dt.tzinfo is None
    assert dt.year == 2026


def test_to_datetime_accepts_date_only() -> None:
    dt = ch._to_datetime("2026-01-01")
    assert dt == _dt.datetime(2026, 1, 1)


def test_build_alternative_estimator() -> None:
    alt = ch._build_alternative({"kind": "estimator", "name": "adaptive_conformal"})
    from lub.challenge import AlternativeEstimator

    assert isinstance(alt, AlternativeEstimator)
    assert alt.name == "adaptive_conformal"


def test_build_alternative_tier() -> None:
    alt = ch._build_alternative({"kind": "tier", "model_id": "claude-sonnet-4-6"})
    from lub.challenge import AlternativeTier

    assert isinstance(alt, AlternativeTier)
    assert alt.model_id == "claude-sonnet-4-6"


def test_build_alternative_threshold_coerces_value() -> None:
    alt = ch._build_alternative({"kind": "threshold", "value": "0.85"})
    from lub.challenge import AlternativeThreshold

    assert isinstance(alt, AlternativeThreshold)
    assert alt.value == pytest.approx(0.85)


def test_build_alternative_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown alternative kind"):
        ch._build_alternative({"kind": "nope"})


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


# ---------------------------------------------------------------------------
# _handle_replay
# ---------------------------------------------------------------------------


def test_handle_replay_maps_engine_output(fake_ledger: _FakeLedgerCM) -> None:
    rep = SimpleNamespace(
        sample_size=42,
        baseline_abstention_rate=0.10,
        counterfactual_abstention_rate=0.07,
        baseline_correctness_rate=0.85,
        counterfactual_correctness_rate=0.83,
        cost_delta_estimate=-1.23,
        audit_trail={"seed": 7},
    )
    engine = MagicMock()
    engine.replay_window.return_value = rep

    with (
        patch("lub.ledger.Ledger", return_value=fake_ledger),
        patch("lub.challenge.ReplayEngine", return_value=engine),
    ):
        out = ch._handle_replay(
            {
                "window": "2026-01-01/2026-02-01",
                "alternative": {"kind": "threshold", "value": 0.7},
            }
        )

    assert out["sample_size"] == 42
    assert out["counterfactual_abstention_rate"] == pytest.approx(0.07)
    assert out["cost_delta_estimate"] == pytest.approx(-1.23)
    assert out["audit_trail"] == {"seed": 7}
    # Engine was driven with parsed datetimes and the built alternative.
    args, _kwargs = engine.replay_window.call_args
    assert args[0] == _dt.datetime(2026, 1, 1)
    assert args[1] == _dt.datetime(2026, 2, 1)
    assert fake_ledger.closed is True


# ---------------------------------------------------------------------------
# _handle_explain_drift
# ---------------------------------------------------------------------------


def test_handle_explain_drift_maps_hypothesis(fake_ledger: _FakeLedgerCM) -> None:
    dh = SimpleNamespace(
        drift_event_id="evt-42",
        hypothesis="distribution shift in branch X",
        support_evidence_ids=["ev-1", "ev-2"],
        similarity_score=0.71,
        metadata={"k": 5},
    )

    with (
        patch("lub.ledger.Ledger", return_value=fake_ledger),
        patch("lub.evidence.EvidenceStore"),
        patch("lub.challenge.explain_drift_event", return_value=dh) as m,
    ):
        out = ch._handle_explain_drift({"event_id": "evt-42", "k": 5})

    assert out["drift_event_id"] == "evt-42"
    assert out["hypothesis"] == "distribution shift in branch X"
    assert out["support_evidence_ids"] == ["ev-1", "ev-2"]
    assert out["similarity_score"] == pytest.approx(0.71)
    assert m.call_args.args[0] == "evt-42"
    assert m.call_args.kwargs["k"] == 5


# ---------------------------------------------------------------------------
# _handle_report
# ---------------------------------------------------------------------------


def test_handle_report_maps_snapshot(fake_ledger: _FakeLedgerCM) -> None:
    snap = SimpleNamespace(ece=0.042)
    report = SimpleNamespace(
        period_start=_dt.datetime(2026, 1, 1),
        period_end=_dt.datetime(2026, 2, 1),
        replay_summary=[{"x": 1}, {"x": 2}, {"x": 3}],
        drift_hypotheses=[{"y": 1}],
        meta_calibration_snapshot=snap,
        recommendations=["tighten threshold"],
    )

    with (
        patch("lub.ledger.Ledger", return_value=fake_ledger),
        patch("lub.evidence.EvidenceStore"),
        patch("lub.challenge.assemble_cec_report", return_value=report),
    ):
        out = ch._handle_report({"period": "2026-01-01/2026-02-01"})

    assert out["period_start"] == "2026-01-01T00:00:00"
    assert out["period_end"] == "2026-02-01T00:00:00"
    assert out["n_replay_scenarios"] == 3
    assert out["n_drift_hypotheses"] == 1
    assert out["meta_calibration_ece"] == pytest.approx(0.042)
    assert out["recommendations"] == ["tighten threshold"]


def test_handle_report_handles_missing_snapshot(fake_ledger: _FakeLedgerCM) -> None:
    report = SimpleNamespace(
        period_start=_dt.datetime(2026, 1, 1),
        period_end=_dt.datetime(2026, 1, 2),
        replay_summary=[],
        drift_hypotheses=[],
        meta_calibration_snapshot=None,
        recommendations=[],
    )

    with (
        patch("lub.ledger.Ledger", return_value=fake_ledger),
        patch("lub.evidence.EvidenceStore"),
        patch("lub.challenge.assemble_cec_report", return_value=report),
    ):
        out = ch._handle_report({"period": "2026-01-01/2026-01-02"})

    assert out["meta_calibration_ece"] is None
    assert out["n_replay_scenarios"] == 0


# ---------------------------------------------------------------------------
# _handle_meta_calibration_curve
# ---------------------------------------------------------------------------


def _fake_curve() -> SimpleNamespace:
    return SimpleNamespace(
        ece=0.05,
        bins=[(0.1, 0.12, 10), (0.5, 0.48, 20), (0.9, 0.88, 15)],
    )


def test_handle_meta_calibration_curve_json_fallback(
    fake_ledger: _FakeLedgerCM, tmp_path: Path
) -> None:
    out_file = tmp_path / "curve.json"
    mc = MagicMock()
    mc.reliability_curve.return_value = _fake_curve()

    # Force the matplotlib path to fail so we exercise the JSON fallback.
    with (
        patch("lub.ledger.Ledger", return_value=fake_ledger),
        patch("lub.challenge.meta_calibration.MetaCalibrator", return_value=mc),
        patch.dict("sys.modules", {"matplotlib": None}),
    ):
        out = ch._handle_meta_calibration_curve(
            {"output_path": str(out_file), "ledger_path": ":memory:"}
        )

    assert out["format"] == "json"
    assert Path(out["path"]).exists()
    data = json.loads(Path(out["path"]).read_text(encoding="utf-8"))
    assert data["ece"] == pytest.approx(0.05)
    assert len(data["bins"]) == 3
    assert data["bins"][0] == {"midpoint": 0.1, "hold_rate": 0.12, "n": 10}


def test_handle_meta_calibration_curve_uses_tempdir_default(
    fake_ledger: _FakeLedgerCM,
) -> None:
    mc = MagicMock()
    mc.reliability_curve.return_value = _fake_curve()

    with (
        patch("lub.ledger.Ledger", return_value=fake_ledger),
        patch("lub.challenge.meta_calibration.MetaCalibrator", return_value=mc),
        patch.dict("sys.modules", {"matplotlib": None}),
    ):
        out = ch._handle_meta_calibration_curve({})

    assert out["format"] == "json"
    p = Path(out["path"])
    assert p.exists()
    # Default filename is lub_cec_meta_calibration.{png|json}; with JSON
    # fallback the extension is rewritten.
    assert p.suffix == ".json"
    assert "lub_cec_meta_calibration" in p.name


def test_handle_meta_calibration_curve_png_when_matplotlib_works(
    fake_ledger: _FakeLedgerCM, tmp_path: Path
) -> None:
    pytest.importorskip("matplotlib")
    mc = MagicMock()
    mc.reliability_curve.return_value = _fake_curve()
    out_file = tmp_path / "curve.png"

    with (
        patch("lub.ledger.Ledger", return_value=fake_ledger),
        patch("lub.challenge.meta_calibration.MetaCalibrator", return_value=mc),
    ):
        out = ch._handle_meta_calibration_curve({"output_path": str(out_file)})

    assert out["format"] == "png"
    p = Path(out["path"])
    assert p.exists()
    assert p.suffix == ".png"
    assert p.stat().st_size > 0


# ---------------------------------------------------------------------------
# build_challenge_tools
# ---------------------------------------------------------------------------


def test_build_challenge_tools_registers_four_tools() -> None:
    tools = ch.build_challenge_tools()
    assert len(tools) == 4
    names = [t.name for t in tools]
    assert names == [
        "lub.challenge.replay",
        "lub.challenge.explain_drift",
        "lub.challenge.report",
        "lub.challenge.meta_calibration_curve",
    ]


def test_build_challenge_tools_wires_correct_schemas() -> None:
    tools = {t.name: t for t in ch.build_challenge_tools()}
    assert tools["lub.challenge.replay"].input_model is ch.ChallengeReplayInput
    assert tools["lub.challenge.replay"].output_model is ch.ChallengeReplayOutput
    assert tools["lub.challenge.explain_drift"].input_model is ch.ExplainDriftInput
    assert tools["lub.challenge.explain_drift"].output_model is ch.ExplainDriftOutput
    assert tools["lub.challenge.report"].input_model is ch.ReportInput
    assert tools["lub.challenge.report"].output_model is ch.ReportOutput
    assert tools["lub.challenge.meta_calibration_curve"].input_model is ch.CurveInput
    assert tools["lub.challenge.meta_calibration_curve"].output_model is ch.CurveOutput


def test_build_challenge_tools_handlers_are_callable() -> None:
    tools = ch.build_challenge_tools()
    for t in tools:
        assert callable(t.handler)
        assert t.description  # non-empty description
