# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""lub.challenge.context_autopilot.reports -- summary report dataclasses.

Two read-only views over a session's Context Autopilot state:

* :class:`ContextWindowReport` -- aggregated turn-by-turn telemetry
  pulled from ``context_window_observations``. The ``observe`` MCP tool
  returns this.
* :class:`EjectionReport` -- summary of which turns were (or would have
  been) ejected at a given threshold. The ``simulate_ejection`` MCP
  tool returns this.

Plus a small :func:`render_markdown` helper so reports can be embedded
in human-readable documents the same way :mod:`lub.challenge.reports`
renders the CEC report.

Spec: planning/25_Context_Autopilot_Spec_2026-04-25.md section 1.4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ContextWindowReport:
    """Aggregated telemetry for one session's context window."""

    session_id: str
    n_turns: int
    total_input_tokens: int
    peak_cumulative_tokens: int
    final_cumulative_tokens: int
    model_max_context: int
    min_headroom_ratio: float
    max_headroom_ratio: float
    final_headroom_ratio: float
    observations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class EjectionReport:
    """Counterfactual summary: 'what would have been ejected at X?'"""

    session_id: str
    threshold: float
    n_candidates: int
    n_ejected: int
    ejected_turn_ids: list[int] = field(default_factory=list)
    score_breakdown: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Loaders -- pull both reports from a Ledger.
# ---------------------------------------------------------------------------


def load_context_window_report(ledger: Any, session_id: str) -> ContextWindowReport:
    """Read every ``context_window_observations`` row for ``session_id``."""
    conn = ledger._conn  # noqa: SLF001
    rows = conn.execute(
        "SELECT turn_id, input_tokens, cumulative_tokens, model_max_context,"
        "  headroom_ratio, observed_at"
        " FROM context_window_observations WHERE session_id = ?"
        " ORDER BY turn_id ASC, id ASC",
        (str(session_id),),
    ).fetchall()

    if not rows:
        return ContextWindowReport(
            session_id=str(session_id),
            n_turns=0,
            total_input_tokens=0,
            peak_cumulative_tokens=0,
            final_cumulative_tokens=0,
            model_max_context=0,
            min_headroom_ratio=1.0,
            max_headroom_ratio=1.0,
            final_headroom_ratio=1.0,
            observations=[],
        )

    obs: list[dict[str, Any]] = []
    cumulatives: list[int] = []
    headrooms: list[float] = []
    total_in = 0
    max_ctx = 0
    for r in rows:
        obs.append(
            {
                "turn_id": int(r[0]),
                "input_tokens": int(r[1]),
                "cumulative_tokens": int(r[2]),
                "model_max_context": int(r[3]),
                "headroom_ratio": float(r[4]),
                "observed_at": str(r[5]),
            }
        )
        total_in += int(r[1])
        cumulatives.append(int(r[2]))
        headrooms.append(float(r[4]))
        max_ctx = max(max_ctx, int(r[3]))

    return ContextWindowReport(
        session_id=str(session_id),
        n_turns=len(rows),
        total_input_tokens=int(total_in),
        peak_cumulative_tokens=int(max(cumulatives)),
        final_cumulative_tokens=int(cumulatives[-1]),
        model_max_context=int(max_ctx),
        min_headroom_ratio=float(min(headrooms)),
        max_headroom_ratio=float(max(headrooms)),
        final_headroom_ratio=float(headrooms[-1]),
        observations=obs,
    )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def render_markdown(report: ContextWindowReport | EjectionReport) -> str:
    """Render a report as a small Markdown block.

    Trades flexibility for boring predictability -- the renderer never
    raises and never reaches for jinja. CEC's report templates are the
    place for richer formatting; this is the dashboard-tile equivalent.
    """
    if isinstance(report, ContextWindowReport):
        return _render_window(report)
    if isinstance(report, EjectionReport):
        return _render_ejection(report)
    raise TypeError(f"unsupported report type: {type(report).__name__}")


def _render_window(r: ContextWindowReport) -> str:
    lines = [
        f"# Context Window Report — session `{r.session_id}`",
        "",
        f"- Turns observed: **{r.n_turns}**",
        f"- Total input tokens: **{r.total_input_tokens}**",
        f"- Peak cumulative tokens: **{r.peak_cumulative_tokens}** "
        f"(model max: {r.model_max_context})",
        f"- Final cumulative tokens: **{r.final_cumulative_tokens}**",
        f"- Headroom ratio: min={r.min_headroom_ratio:.3f}, final={r.final_headroom_ratio:.3f}",
    ]
    return "\n".join(lines) + "\n"


def _render_ejection(r: EjectionReport) -> str:
    lines = [
        f"# Ejection Report — session `{r.session_id}`",
        "",
        f"- Threshold: **{r.threshold:.3f}**",
        f"- Candidates scored: **{r.n_candidates}**",
        f"- Turns ejected: **{r.n_ejected}**",
    ]
    if r.ejected_turn_ids:
        ids = ", ".join(str(i) for i in r.ejected_turn_ids)
        lines.append(f"- Ejected turn ids: {ids}")
    return "\n".join(lines) + "\n"


__all__ = [
    "ContextWindowReport",
    "EjectionReport",
    "load_context_window_report",
    "render_markdown",
]
