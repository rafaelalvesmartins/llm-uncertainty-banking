# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Shared pydantic IO models for the auto-generated MCP tool surface.

The hand-written tools in :mod:`lub.mcp.server` use bespoke schemas
because each one wraps a non-trivial workflow (cascaded answer, AI-RMF
report). The auto-generated tools in :mod:`lub.mcp.tools` wrap a single
estimator or metric and share the two schemas defined here so introspection,
documentation, and testing only need to know two shapes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["EstimatorInput", "EstimatorOutput", "MetricInput", "MetricOutput"]


class EstimatorInput(BaseModel):
    """Input for any auto-wrapped uncertainty estimator tool.

    The estimator runs against ``DummyBackend`` only — agent-loop callers
    of MCP should not be able to spend external-API budget without
    explicit operator setup. To use a real backend, build a pipeline in
    Python directly.
    """

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(..., description="The text to score.")
    backend_model_id: str = Field(
        default="dummy-0",
        description="DummyBackend model_id (label only — no real model is invoked).",
    )
    estimator_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Forwarded to the estimator constructor (e.g. n_samples=5).",
    )


class EstimatorOutput(BaseModel):
    """Output of any auto-wrapped uncertainty estimator tool."""

    model_config = ConfigDict(extra="forbid")

    estimator: str = Field(..., description="Estimator REGISTRY_KEY.")
    answer: str = Field(..., description="The generated answer string.")
    confidence: float = Field(..., ge=0.0, le=1.0)
    raw_scores: dict[str, float] = Field(default_factory=dict)
    should_refuse: bool


class MetricInput(BaseModel):
    """Input for any auto-wrapped calibration-metric tool.

    Most metrics in :mod:`lub.calibration` take two parallel arrays:
    a confidence vector in ``[0, 1]`` and a correctness vector in
    ``{0, 1}``. The few metrics with non-standard signatures (e.g.
    ``compute_all``, ``analyze_drift``) are not auto-wrapped.
    """

    model_config = ConfigDict(extra="forbid")

    confidences: list[float] = Field(..., description="Per-prediction confidence in [0, 1].")
    correct: list[float] = Field(..., description="Per-prediction correctness in {0, 1}.")
    metric_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Forwarded to the metric (e.g. n_bins=10).",
    )


class MetricOutput(BaseModel):
    """Output of any auto-wrapped calibration-metric tool."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    value: float
    description: str
