# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :mod:`lub.mcp.tools.challenge`."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lub.mcp.tools import challenge as mod
from lub.mcp.tools.challenge import (
    ChallengeReplayInput,
    ChallengeReplayOutput,
    CurveInput,
    CurveOutput,
    ExplainDriftInput,
    ExplainDriftOutput,
    ReportInput,
    ReportOutput,
    _build_alternative,
    _handle_explain_drift,
    _handle_meta_calibration_curve,
    _handle_replay,
    _handle_report,
    _parse_interval,
    _to_datetime,
    build_challenge_tools,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_ledger_cm():
    """Build a context-manager mock that mimics ``Ledger(path)``."""
    led = MagicMock(name="ledger")
    cm = MagicMock(name="ledger_cm")
    cm.__enter__ = MagicMock(return_value=led)
    cm.__exit__ = MagicMock(return_value=False)
    return cm, led


@pytest.fixture
def fake_replay_report():
    return SimpleNamespace(
        sample_size=12,
        baseline_abstention_rate=0.1,
        counterfactual_abstention_rate=0.2,
        baseline_correctness_rate=0.9,
        counterfactual_correctness_rate=0.85,
        cost_delta_estimate=-1.5,
        audit_trail={"engine": "replay"},
    )


@pytest.fixture
def fake_drift_hypothesis():
    return SimpleNamespace(
        drift_event_id="evt-1",
        hypothesis="prompt distribution drifted toward longer questions",
        support_evidence_ids=["ev-1", "ev-2"],
        similarity_score=0.42,
        metadata={"window": "1h"},
    )


@pytest.fixture
def fake_cec_report():
    snap = SimpleNamespace(ece=0.07)
    return SimpleNamespace(
        period_start=datetime(2026, 4, 1, 0, 0),
        period_end=datetime(2026, 4, 30, 0, 0),
        replay_summary=[object(), object(), object()],
        drift_hypotheses=[object()],
        meta_calibration_snapshot=snap,
        recommendations=["raise threshold", "retire stale tier"],
    )


@pytest.fixture
def fake_curve():
    return SimpleNamespace(
        ece=0.123,
        bins=[(0.1, 0.05, 10), (0.5, 0.55, 20), (0.9, 0.92, 30)],
    )


# ---------------------------------------------------------------------------
# _parse_interval
# ---------------------------------------------------------------------------


def test_parse_interval_splits_on_slash():
    start, end = _parse_interval("2026-04-01/2026-04-30")
    assert start == "2026-04-01"
    assert end == "2026-04-30"


def test_parse_interval_strips_whitespace():
    start, end = _parse_interval(" 2026-04-01 / 2026-04-30 ")
    assert start == "2026-04-01"
    assert end == "2026-04-30"


def test_parse_interval_missing_slash_raises():
    with pytest.raises(ValueError, match="ISO interval"):
        _parse_interval("2026-04-01")


# ---------------------------------------------------------------------------
# _to_datetime
# ---------------------------------------------------------------------------


def test_to_datetime_parses_plain_iso():
    dt = _to_datetime("2026-04-01T12:30:00")
    assert dt == datetime(2026, 4, 1, 12, 30, 0)
    assert dt.tzinfo is None


def test_to_datetime_strips_tzinfo_when_z_suffix():
    dt = _to_datetime("2026-04-01T12:30:00Z")
    assert dt == datetime(2026, 4, 1, 12, 30, 0)
    assert dt.tzinfo is None


def test_to_datetime_accepts_date_only():
    dt = _to_datetime("2026-04-01")
    assert dt == datetime(2026, 4, 1)


# ---------------------------------------------------------------------------
# _build_alternative
# ---------------------------------------------------------------------------


def test_build_alternative_estimator():
    fake_est = MagicMock(name="AlternativeEstimator")
    fake_tier = MagicMock(name="AlternativeTier")
    fake_thr = MagicMock(name="AlternativeThreshold")
    with patch.dict(
        "sys.modules",
        {"lub.challenge": SimpleNamespace(
            AlternativeEstimator=fake_est,
            AlternativeTier=fake_tier,
            AlternativeThreshold=fake_thr,
        )},
    ):
        result = _build_alternative({"kind": "estimator", "name": "adaptive_conformal"})
    fake_est.assert_called_once_with(name="adaptive_conformal")
    assert result is fake_est.return_value


def test_build_alternative_tier():
    fake_est = MagicMock()
    fake_tier = MagicMock()
    fake_thr = MagicMock()
    with patch.dict(
        "sys.modules",
        {"lub.challenge": SimpleNamespace(
            AlternativeEstimator=fake_est,
            AlternativeTier=fake_tier,
            AlternativeThreshold=fake_thr,
        )},
    ):
        result = _build_alternative({"kind": "tier", "model_id": "claude-sonnet-4-6"})
    fake_tier.assert_called_once_with(model_id="claude-sonnet-4-6")
    assert result is fake_tier.return_value


def test_build_alternative_threshold_coerces_to_float():
    fake_est = MagicMock()
    fake_tier = MagicMock()
    fake_thr = MagicMock()
    with patch.dict(
        "sys.modules",
        {"lub.challenge": SimpleNamespace(
            AlternativeEstimator=fake_est,
            AlternativeTier=fake_tier,
            AlternativeThreshold=fake_thr,
        )},
    ):
        _build_alternative({"kind": "threshold", "value": "0.85"})
    fake_thr.assert_called_once_with(value=0.85)


def test_build_alternative_unknown_kind_raises():
    fake_est = MagicMock()
    fake_tier = MagicMock()
    fake_thr = MagicMock()
    with patch.dict(
        "sys.modules",
        {"lub.challenge": SimpleNamespace(
            AlternativeEstimator=fake_est,
            AlternativeTier=fake_tier,
            AlternativeThreshold=fake_thr,
        )},
    ):
        with pytest.raises(ValueError, match="unknown alternative kind"):
            _build_alternative({"kind": "magic"})


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


def test_replay_input_rejects_extra_fields():
    with pytest.raises(Exception):
        ChallengeReplayInput.model_validate(
            {
                "window": "2026-04-01/2026-04-30",
                "alternative": {"kind": "tier", "model_id": "x"},
                "extra": "nope",
            }
        )


def test_replay_input_defaults_in_memory_ledger():
    inp = ChallengeReplayInput.model_validate(
        {"window": "2026-04-01/2026-04-30", "alternative": {"kind": "tier", "model_id": "x"}}
    )
    assert inp.ledger_path == ":memory:"


def test_explain_drift_input_k_bounds():
    with pytest.raises(Exception):
        ExplainDriftInput.model_validate({"event_id": "e1", "k": 0})
    with pytest.raises(Exception):
        ExplainDriftInput.model_validate({"event_id": "e1", "k": 51})
    inp = ExplainDriftInput.model_validate({"event_id": "e1", "k": 5})
    assert inp.k == 5


def test_curve_input_optional_output_path():
    inp = CurveInput.model_validate({})
    assert inp.output_path is None
    assert inp.ledger_path == ":memory:"


def test_replay_output_audit_trail_default():
    out = ChallengeReplayOutput(
        sample_size=0,
        baseline_abstention_rate=0.0,
        counterfactual_abstention_rate=0.0,
        cost_delta_estimate=0.0,
    )
    assert out.audit_trail == {}
    assert out.baseline_correctness_rate is None


def test_explain_drift_output_defaults():
    out = ExplainDriftOutput(drift_event_id="e", hypothesis="h")
    assert out.support_evidence_ids == []
    assert out.similarity_score == 0.0
    assert out.metadata == {}


def test_report_output_recommendations_default():
    out = ReportOutput(
        period_start="2026-04-01",
        period_end="2026-04-30",
        n_replay_scenarios=0,
        n_drift_hypotheses=0,
    )
    assert out.recommendations == []
    assert out.meta_calibration_ece is None


# ---------------------------------------------------------------------------
# _handle_replay
# ---------------------------------------------------------------------------


def test_handle_replay_invokes_engine_and_returns_dump(
    fake_ledger_cm, fake_replay_report
):
    cm, led = fake_ledger_cm
    engine = MagicMock()
    engine.replay_window.return_value = fake_replay_report

    fake_alt = MagicMock(name="alternative")
    with patch.object(mod, "_build_alternative", return_value=fake_alt) as mk_alt, \
        patch.dict(
            "sys.modules",
            {
                "lub.challenge": SimpleNamespace(ReplayEngine=lambda ledger: engine),
                "lub.ledger": SimpleNamespace(Ledger=lambda p: cm),
            },
        ):
        out = _handle_replay(
            {
                "window": "2026-04-01T00:00:00/2026-04-30T00:00:00",
                "alternative": {"kind": "tier", "model_id": "claude-sonnet-4-6"},
                "ledger_path": ":memory:",
            }
        )

    mk_alt.assert_called_once_with({"kind": "tier", "model_id": "claude-sonnet-4-6"})
    engine.replay_window.assert_called_once()
    args, _ = engine.replay_window.call_args
    assert args[0] == datetime(2026, 4, 1)
    assert args[1] == datetime(2026, 4, 30)
    assert args[2] is fake_alt

    assert out["sample_size"] == 12
    assert out["baseline_abstention_rate"] == 0.1
    assert out["counterfactual_abstention_rate"] == 0.2
    assert out["audit_trail"] == {"engine": "replay"}


def test_handle_replay_bad_window_raises(fake_ledger_cm):
    cm, _ = fake_ledger_cm
    engine = MagicMock()
    with patch.dict(
        "sys.modules",
        {
            "lub.challenge": SimpleNamespace(
                ReplayEngine=lambda ledger: engine,
                AlternativeEstimator=MagicMock(),
                AlternativeTier=MagicMock(),
                AlternativeThreshold=MagicMock(),
            ),
            "lub.ledger": SimpleNamespace(Ledger=lambda p: cm),
        },
    ):
        with pytest.raises(ValueError, match="ISO interval"):
            _handle_replay(
                {
                    "window": "no-slash",
                    "alternative": {"kind": "tier", "model_id": "x"},
                }
            )


# ---------------------------------------------------------------------------
# _handle_explain_drift
# ---------------------------------------------------------------------------


def test_handle_explain_drift_returns_dump(fake_ledger_cm, fake_drift_hypothesis):
    cm, led = fake_ledger_cm
    explain_fn = MagicMock(return_value=fake_drift_hypothesis)
    store_cls = MagicMock(name="EvidenceStore")

    with patch.dict(
        "sys.modules",
        {
            "lub.challenge": SimpleNamespace(explain_drift_event=explain_fn),
            "lub.ledger": SimpleNamespace(Ledger=lambda p: cm),
            "lub.evidence": SimpleNamespace(EvidenceStore=store_cls),
        },
    ):
        out = _handle_explain_drift({"event_id": "evt-1", "k": 7})

    explain_fn.assert_called_once_with(
        "evt-1", ledger=led, evidence_store=store_cls.return_value, k=7
    )
    assert out["drift_event_id"] == "evt-1"
    assert out["hypothesis"].startswith("prompt distribution")
    assert out["support_evidence_ids"] == ["ev-1", "ev-2"]
    assert out["similarity_score"] == pytest.approx(0.42)
    assert out["metadata"] == {"window": "1h"}


# ---------------------------------------------------------------------------
# _handle_report
# ---------------------------------------------------------------------------


def test_handle_report_returns_dump(fake_ledger_cm, fake_cec_report):
    cm, led = fake_ledger_cm
    assemble = MagicMock(return_value=fake_cec_report)
    store_cls = MagicMock(name="EvidenceStore")

    with patch.dict(
        "sys.modules",
        {
            "lub.challenge": SimpleNamespace(assemble_cec_report=assemble),
            "lub.ledger": SimpleNamespace(Ledger=lambda p: cm),
            "lub.evidence": SimpleNamespace(EvidenceStore=store_cls),
        },
    ):
        out = _handle_report({"period": "2026-04-01/2026-04-30"})

    assemble.assert_called_once()
    args, kwargs = assemble.call_args
    assert args[0] == datetime(2026, 4, 1)
    assert args[1] == datetime(2026, 4, 30)
    assert kwargs["ledger"] is led
    assert kwargs["evidence_store"] is store_cls.return_value

    assert out["period_start"] == "2026-04-01T00:00:00"
    assert out["period_end"] == "2026-04-30T00:00:00"
    assert out["n_replay_scenarios"] == 3
    assert out["n_drift_hypotheses"] == 1
    assert out["meta_calibration_ece"] == pytest.approx(0.07)
    assert out["recommendations"] == ["raise threshold", "retire stale tier"]


def test_handle_report_handles_missing_meta_snapshot(fake_ledger_cm):
    cm, _ = fake_ledger_cm
    report = SimpleNamespace(
        period_start=datetime(2026, 4, 1),
        period_end=datetime(2026, 4, 2),
        replay_summary=[],
        drift_hypotheses=[],
        meta_calibration_snapshot=None,
        recommendations=[],
    )
    with patch.dict(
        "sys.modules",
        {
            "lub.challenge": SimpleNamespace(assemble_cec_report=lambda *a, **k: report),
            "lub.ledger": SimpleNamespace(Ledger=lambda p: cm),
            "lub.evidence": SimpleNamespace(EvidenceStore=MagicMock()),
        },
    ):
        out = _handle_report({"period": "2026-04-01/2026-04-02"})

    assert out["meta_calibration_ece"] is None
    assert out["n_replay_scenarios"] == 0
    assert out["n_drift_hypotheses"] == 0


# ---------------------------------------------------------------------------
# _handle_meta_calibration_curve
# ---------------------------------------------------------------------------


def test_handle_curve_json_fallback_when_matplotlib_unavailable(
    tmp_path, fake_ledger_cm, fake_curve, monkeypatch
):
    cm, _ = fake_ledger_cm
    mc = MagicMock()
    mc.reliability_curve.return_value = fake_curve

    target = tmp_path / "curve.png"

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("matplotlib"):
            raise ImportError("simulated: matplotlib not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with patch.dict(
        "sys.modules",
        {
            "lub.challenge.meta_calibration": SimpleNamespace(
                MetaCalibrator=lambda ledger: mc
            ),
            "lub.ledger": SimpleNamespace(Ledger=lambda p: cm),
        },
    ):
        out = _handle_meta_calibration_curve(
            {"output_path": str(target), "ledger_path": ":memory:"}
        )

    written = Path(out["path"])
    assert out["format"] == "json"
    assert written.suffix == ".json"
    assert written.exists()
    parsed = json.loads(written.read_text(encoding="utf-8"))
    assert parsed["ece"] == pytest.approx(0.123)
    assert len(parsed["bins"]) == 3
    assert parsed["bins"][0] == {"midpoint": 0.1, "hold_rate": 0.05, "n": 10}


def test_handle_curve_uses_temp_dir_when_no_output_path(
    fake_ledger_cm, fake_curve, monkeypatch, tmp_path
):
    cm, _ = fake_ledger_cm
    mc = MagicMock()
    mc.reliability_curve.return_value = fake_curve

    monkeypatch.setattr(mod.tempfile, "gettempdir", lambda: str(tmp_path))

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("matplotlib"):
            raise ImportError("force JSON path")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with patch.dict(
        "sys.modules",
        {
            "lub.challenge.meta_calibration": SimpleNamespace(
                MetaCalibrator=lambda ledger: mc
            ),
            "lub.ledger": SimpleNamespace(Ledger=lambda p: cm),
        },
    ):
        out = _handle_meta_calibration_curve({})

    written = Path(out["path"])
    assert out["format"] == "json"
    assert written.parent == tmp_path
    assert written.name == "lub_cec_meta_calibration.json"
    assert written.exists()


# ---------------------------------------------------------------------------
# build_challenge_tools
# ---------------------------------------------------------------------------


def test_build_challenge_tools_returns_four_tools_with_expected_names():
    tools = build_challenge_tools()
    assert len(tools) == 4
    names = [t.name for t in tools]
    assert names == [
        "lub.challenge.replay",
        "lub.challenge.explain_drift",
        "lub.challenge.report",
        "lub.challenge.meta_calibration_curve",
    ]


def test_build_challenge_tools_wires_models_and_handlers():
    tools = {t.name: t for t in build_challenge_tools()}
    replay = tools["lub.challenge.replay"]
    assert replay.input_model is ChallengeReplayInput
    assert replay.output_model is ChallengeReplayOutput
    assert replay.handler is _handle_replay

    drift = tools["lub.challenge.explain_drift"]
    assert drift.input_model is ExplainDriftInput
    assert drift.output_model is ExplainDriftOutput
    assert drift.handler is _handle_explain_drift

    report = tools["lub.challenge.report"]
    assert report.input_model is ReportInput
    assert report.output_model is ReportOutput
    assert report.handler is _handle_report

    curve = tools["lub.challenge.meta_calibration_curve"]
    assert curve.input_model is CurveInput
    assert curve.output_model is CurveOutput
    assert curve.handler is _handle_meta_calibration_curve
