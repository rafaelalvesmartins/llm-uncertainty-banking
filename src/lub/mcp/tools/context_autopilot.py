# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Auto-wrapped MCP tools for :mod:`lub.challenge.context_autopilot`.

Two read-only tools:

* ``lub.challenge.context_autopilot.observe`` -- summarise a session's
  context-window observations (``ContextWindowReport``).
* ``lub.challenge.context_autopilot.simulate_ejection`` -- counterfactual
  "what would have been ejected at this threshold?" report
  (``EjectionReport``).

Both are hermetic: they read existing rows from the ledger and never
make a model call. Pattern mirrors :mod:`lub.mcp.tools.challenge`.

Spec: planning/25_Context_Autopilot_Spec_2026-04-25.md section 1.4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from lub.mcp.server import ToolDef


# ---------------------------------------------------------------------------
# Pydantic IO schemas
# ---------------------------------------------------------------------------


class ObserveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., description="Session identifier to summarise.")
    ledger_path: str = Field(
        default=":memory:",
        description="Path to the ledger SQLite file. ':memory:' is allowed.",
    )


class ObserveOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    n_turns: int
    total_input_tokens: int
    peak_cumulative_tokens: int
    final_cumulative_tokens: int
    model_max_context: int
    min_headroom_ratio: float
    max_headroom_ratio: float
    final_headroom_ratio: float
    observations: list[dict[str, Any]] = Field(default_factory=list)


class SimulateEjectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., description="Session identifier.")
    threshold: float = Field(..., ge=0.0, le=10.0, description="Ejection score threshold to test.")
    ledger_path: str = Field(default=":memory:")
    k: int = Field(default=10, ge=1, le=1000, description="Maximum turns to eject.")
    alpha: float = Field(default=0.5, ge=0.0, le=10.0)
    beta: float = Field(default=0.2, ge=0.0, le=10.0)
    gamma: float = Field(default=0.3, ge=0.0, le=10.0)
    current_query: str = Field(
        default="",
        description="Most recent input the existing context is competing against.",
    )
    turns: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Optional list of {turn_id, text, age_in_turns} dicts. "
            "When empty, the tool returns a no-op report (ledger does "
            "not store turn text)."
        ),
    )


class SimulateEjectionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    threshold: float
    n_candidates: int
    n_ejected: int
    ejected_turn_ids: list[int] = Field(default_factory=list)
    score_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_observe(payload: dict[str, Any]) -> dict[str, Any]:
    from lub.challenge.context_autopilot.reports import (
        load_context_window_report,
    )
    from lub.ledger import Ledger

    args = ObserveInput.model_validate(payload)
    with Ledger(args.ledger_path) as led:
        report = load_context_window_report(led, args.session_id)

    return ObserveOutput(
        session_id=report.session_id,
        n_turns=report.n_turns,
        total_input_tokens=report.total_input_tokens,
        peak_cumulative_tokens=report.peak_cumulative_tokens,
        final_cumulative_tokens=report.final_cumulative_tokens,
        model_max_context=report.model_max_context,
        min_headroom_ratio=report.min_headroom_ratio,
        max_headroom_ratio=report.max_headroom_ratio,
        final_headroom_ratio=report.final_headroom_ratio,
        observations=list(report.observations),
    ).model_dump()


def _handle_simulate_ejection(payload: dict[str, Any]) -> dict[str, Any]:
    from lub.challenge.context_autopilot import (
        EjectionReport,
        Turn,
        eject_top_k,
    )
    from lub.evidence import EvidenceStore
    from lub.ledger import Ledger

    args = SimulateEjectionInput.model_validate(payload)
    turns: list[Turn] = [
        Turn(
            turn_id=int(t.get("turn_id", i)),
            text=str(t.get("text", "")),
            age_in_turns=int(t.get("age_in_turns", 0)),
        )
        for i, t in enumerate(args.turns)
    ]

    with Ledger(args.ledger_path) as led:
        store = EvidenceStore()
        ejected = eject_top_k(
            turns,
            args.current_query,
            store,
            led,
            k=args.k,
            threshold=args.threshold,
            alpha=args.alpha,
            beta=args.beta,
            gamma=args.gamma,
            session_id=args.session_id,
            persist=False,
        )

    breakdown = [
        {
            "turn_id": e.turn_id,
            "score": e.score.score,
            "similarity_term": e.score.similarity_term,
            "age_term": e.score.age_term,
            "usefulness_term": e.score.usefulness_term,
            "similarity": e.score.similarity,
            "age_normalised": e.score.age_normalised,
            "historical_usefulness": e.score.historical_usefulness,
        }
        for e in ejected
    ]

    report = EjectionReport(
        session_id=args.session_id,
        threshold=args.threshold,
        n_candidates=len(turns),
        n_ejected=len(ejected),
        ejected_turn_ids=[int(e.turn_id) for e in ejected],
        score_breakdown=breakdown,
        metadata={
            "alpha": args.alpha,
            "beta": args.beta,
            "gamma": args.gamma,
            "k": args.k,
            "persist": False,
        },
    )

    return SimulateEjectionOutput(
        session_id=report.session_id,
        threshold=report.threshold,
        n_candidates=report.n_candidates,
        n_ejected=report.n_ejected,
        ejected_turn_ids=list(report.ejected_turn_ids),
        score_breakdown=list(report.score_breakdown),
        metadata=dict(report.metadata),
    ).model_dump()


# ---------------------------------------------------------------------------
# Tool builder
# ---------------------------------------------------------------------------


def build_context_autopilot_tools() -> list[ToolDef]:
    """Return the two Context Autopilot MCP tools."""
    from lub.mcp.server import ToolDef

    return [
        ToolDef(
            name="lub.challenge.context_autopilot.observe",
            description=(
                "Summarise a session's context-window observations "
                "(turn-by-turn token usage, peak cumulative tokens, "
                "min/max headroom ratios)."
            ),
            input_model=ObserveInput,
            output_model=ObserveOutput,
            handler=_handle_observe,
        ),
        ToolDef(
            name="lub.challenge.context_autopilot.simulate_ejection",
            description=(
                "Counterfactual: score the supplied context turns "
                "against the current_query and return what would have "
                "been ejected at the given threshold (read-only — no "
                "ledger writes)."
            ),
            input_model=SimulateEjectionInput,
            output_model=SimulateEjectionOutput,
            handler=_handle_simulate_ejection,
        ),
    ]


__all__ = ["build_context_autopilot_tools"]
