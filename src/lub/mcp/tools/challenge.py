# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Auto-wrapped MCP tools for :mod:`lub.challenge`.

Four read-only tools:

* ``lub.challenge.replay`` — counterfactual replay over a window.
* ``lub.challenge.explain_drift`` — hypothesis for one drift event.
* ``lub.challenge.report`` — full CEC periodic report (JSON snapshot).
* ``lub.challenge.meta_calibration_curve`` — write the curve to disk
  and return the artifact path (PNG via matplotlib if available, JSON
  fallback otherwise).

Computation delegates entirely to :mod:`lub.challenge`. No real LLM
calls are made — the tools are hermetic.

Spec: planning/24_CEC_Spec_2026-04-25.md §1.4 + §4 step 7.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from lub.mcp.server import ToolDef


# ---------------------------------------------------------------------------
# Pydantic IO schemas
# ---------------------------------------------------------------------------


class ChallengeReplayInput(BaseModel):
    """Input for the ``lub.challenge.replay`` tool.

    The ``window`` string is parsed as ``"<start_iso>/<end_iso>"`` (a
    common ISO 8601 interval shorthand). Either side may be a date or
    a datetime in ISO format.

    The ``alternative`` dict has shape ``{"kind": "...", ...}``:

    * ``{"kind": "estimator", "name": "adaptive_conformal"}``
    * ``{"kind": "tier", "model_id": "claude-sonnet-4-6"}``
    * ``{"kind": "threshold", "value": 0.85}``
    """

    model_config = ConfigDict(extra="forbid")

    window: str = Field(..., description="ISO interval 'start/end' covering the replay window.")
    alternative: dict[str, Any] = Field(
        ..., description="Alternative descriptor — see class docstring."
    )
    ledger_path: str = Field(
        default=":memory:",
        description="Path to the ledger SQLite file. ':memory:' is allowed.",
    )


class ChallengeReplayOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_size: int
    baseline_abstention_rate: float
    counterfactual_abstention_rate: float
    baseline_correctness_rate: float | None = None
    counterfactual_correctness_rate: float | None = None
    cost_delta_estimate: float
    audit_trail: dict[str, Any] = Field(default_factory=dict)


class ExplainDriftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    ledger_path: str = ":memory:"
    k: int = Field(default=5, ge=1, le=50)


class ExplainDriftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drift_event_id: str
    hypothesis: str
    support_evidence_ids: list[str] = Field(default_factory=list)
    similarity_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReportInput(BaseModel):
    """Input for ``lub.challenge.report``.

    ``period`` is an ISO interval ``"start/end"`` like
    :class:`ChallengeReplayInput.window`.
    """

    model_config = ConfigDict(extra="forbid")

    period: str
    ledger_path: str = ":memory:"


class ReportOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_start: str
    period_end: str
    n_replay_scenarios: int
    n_drift_hypotheses: int
    meta_calibration_ece: float | None = None
    recommendations: list[str] = Field(default_factory=list)


class CurveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ledger_path: str = ":memory:"
    output_path: str | None = None


class CurveOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    format: str  # "png" or "json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_interval(s: str) -> tuple[str, str]:
    if "/" not in s:
        raise ValueError(f"window/period must be 'start/end' ISO interval, got {s!r}")
    start, end = s.split("/", 1)
    return start.strip(), end.strip()


def _to_datetime(s: str) -> Any:
    from datetime import datetime

    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def _build_alternative(payload: dict[str, Any]) -> Any:
    from lub.challenge import (
        AlternativeEstimator,
        AlternativeThreshold,
        AlternativeTier,
    )

    kind = payload.get("kind")
    if kind == "estimator":
        return AlternativeEstimator(name=str(payload["name"]))
    if kind == "tier":
        return AlternativeTier(model_id=str(payload["model_id"]))
    if kind == "threshold":
        return AlternativeThreshold(value=float(payload["value"]))
    raise ValueError(
        f"unknown alternative kind {kind!r}; expected 'estimator', 'tier', or 'threshold'"
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_replay(payload: dict[str, Any]) -> dict[str, Any]:
    from lub.challenge import ReplayEngine
    from lub.ledger import Ledger

    args = ChallengeReplayInput.model_validate(payload)
    start_s, end_s = _parse_interval(args.window)
    start, end = _to_datetime(start_s), _to_datetime(end_s)
    alternative = _build_alternative(args.alternative)

    with Ledger(args.ledger_path) as led:
        engine = ReplayEngine(ledger=led)
        rep = engine.replay_window(start, end, alternative)

    return ChallengeReplayOutput(
        sample_size=rep.sample_size,
        baseline_abstention_rate=rep.baseline_abstention_rate,
        counterfactual_abstention_rate=rep.counterfactual_abstention_rate,
        baseline_correctness_rate=rep.baseline_correctness_rate,
        counterfactual_correctness_rate=rep.counterfactual_correctness_rate,
        cost_delta_estimate=rep.cost_delta_estimate,
        audit_trail=rep.audit_trail,
    ).model_dump()


def _handle_explain_drift(payload: dict[str, Any]) -> dict[str, Any]:
    from lub.challenge import explain_drift_event
    from lub.evidence import EvidenceStore
    from lub.ledger import Ledger

    args = ExplainDriftInput.model_validate(payload)
    with Ledger(args.ledger_path) as led:
        store = EvidenceStore()
        dh = explain_drift_event(args.event_id, ledger=led, evidence_store=store, k=args.k)

    return ExplainDriftOutput(
        drift_event_id=dh.drift_event_id,
        hypothesis=dh.hypothesis,
        support_evidence_ids=list(dh.support_evidence_ids),
        similarity_score=dh.similarity_score,
        metadata=dict(dh.metadata),
    ).model_dump()


def _handle_report(payload: dict[str, Any]) -> dict[str, Any]:
    from lub.challenge import assemble_cec_report
    from lub.evidence import EvidenceStore
    from lub.ledger import Ledger

    args = ReportInput.model_validate(payload)
    start_s, end_s = _parse_interval(args.period)
    start, end = _to_datetime(start_s), _to_datetime(end_s)

    with Ledger(args.ledger_path) as led:
        store = EvidenceStore()
        report = assemble_cec_report(start, end, ledger=led, evidence_store=store)

    snap = report.meta_calibration_snapshot
    return ReportOutput(
        period_start=report.period_start.isoformat(),
        period_end=report.period_end.isoformat(),
        n_replay_scenarios=len(report.replay_summary),
        n_drift_hypotheses=len(report.drift_hypotheses),
        meta_calibration_ece=(snap.ece if snap is not None else None),
        recommendations=list(report.recommendations),
    ).model_dump()


def _handle_meta_calibration_curve(payload: dict[str, Any]) -> dict[str, Any]:
    """Write the curve as PNG (matplotlib) or JSON fallback, return path."""
    from lub.challenge.meta_calibration import MetaCalibrator
    from lub.ledger import Ledger

    args = CurveInput.model_validate(payload)
    with Ledger(args.ledger_path) as led:
        mc = MetaCalibrator(ledger=led)
        curve = mc.reliability_curve()

    if args.output_path is not None:
        out_path = Path(args.output_path)
    else:
        out_path = Path(tempfile.gettempdir()) / "lub_cec_meta_calibration.png"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fmt: str
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(4, 4))
        if curve.bins:
            xs = [b[0] for b in curve.bins]
            ys = [b[1] for b in curve.bins]
            ax.plot([0.0, 1.0], [0.0, 1.0], "--", color="grey", linewidth=0.8)
            ax.plot(xs, ys, marker="o")
        ax.set_xlim(0.0, 1.0)
        ax.set_ylim(0.0, 1.0)
        ax.set_xlabel("Predicted confidence")
        ax.set_ylabel("Observed hold rate")
        ax.set_title(f"CEC meta-calibration (ECE={curve.ece:.3f})")
        fig.tight_layout()
        if out_path.suffix.lower() != ".png":
            out_path = out_path.with_suffix(".png")
        fig.savefig(str(out_path), dpi=120)
        plt.close(fig)
        fmt = "png"
    except Exception:
        # JSON fallback when matplotlib is unavailable / fails.
        if out_path.suffix.lower() != ".json":
            out_path = out_path.with_suffix(".json")
        out_path.write_text(
            json.dumps(
                {
                    "ece": curve.ece,
                    "bins": [{"midpoint": m, "hold_rate": h, "n": n} for m, h, n in curve.bins],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        fmt = "json"

    return CurveOutput(path=str(out_path), format=fmt).model_dump()


# ---------------------------------------------------------------------------
# Tool builder
# ---------------------------------------------------------------------------


def build_challenge_tools() -> list[ToolDef]:
    """Return the four CEC MCP tools."""
    from lub.mcp.server import ToolDef

    return [
        ToolDef(
            name="lub.challenge.replay",
            description=(
                "Replay a window of the lub.ledger through an alternative "
                "estimator/tier/threshold and return counterfactual "
                "abstention + correctness + cost delta."
            ),
            input_model=ChallengeReplayInput,
            output_model=ChallengeReplayOutput,
            handler=_handle_replay,
        ),
        ToolDef(
            name="lub.challenge.explain_drift",
            description=(
                "Generate a one-paragraph rule-based hypothesis for a "
                "drift event with k-NN historical support."
            ),
            input_model=ExplainDriftInput,
            output_model=ExplainDriftOutput,
            handler=_handle_explain_drift,
        ),
        ToolDef(
            name="lub.challenge.report",
            description=(
                "Assemble a periodic CEC report (replay + drift hypotheses "
                "+ meta-calibration snapshot + recommendations)."
            ),
            input_model=ReportInput,
            output_model=ReportOutput,
            handler=_handle_report,
        ),
        ToolDef(
            name="lub.challenge.meta_calibration_curve",
            description=(
                "Write the meta-calibration reliability curve to disk "
                "(PNG via matplotlib if available, JSON fallback) and "
                "return the artifact path."
            ),
            input_model=CurveInput,
            output_model=CurveOutput,
            handler=_handle_meta_calibration_curve,
        ),
    ]


__all__ = ["build_challenge_tools"]
