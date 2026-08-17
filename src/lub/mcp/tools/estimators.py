# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Auto-generate one MCP tool per public uncertainty estimator.

Discovery walks ``lub.uncertainty._LAZY_MAP`` so a new estimator added
to the lazy-load registry automatically gets an MCP tool with no extra
glue. The tool name is ``lub.estimator.<REGISTRY_KEY>``.

All wrapped tools run against ``DummyBackend`` only. To score real
LLM output, callers should build a pipeline in Python directly — MCP
tools are intentionally cheap-and-hermetic so an agent loop can iterate
without burning external-API budget.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from lub.mcp.schemas import EstimatorInput, EstimatorOutput

if TYPE_CHECKING:
    from lub.mcp.server import ToolDef


__all__ = ["build_estimator_tools"]

_LOG = structlog.get_logger(__name__)


# Estimators that require special construction or external dependencies
# beyond what DummyBackend exposes. They're skipped from the auto-wrap;
# the existing hand-written tools in lub.mcp.server cover the workflow
# variants of these (p_true via score_with_p_true, etc.).
_SKIP: frozenset[str] = frozenset(
    {
        "MCDropoutEstimator",  # needs torch model with dropout layers
        "EigenScoreEstimator",  # needs hidden-state extraction
        "MahalanobisEstimator",  # needs reference distribution fit
        "EnsembleEstimator",  # needs multiple backends
        "LMPolygraphEstimator",  # optional dep (lub[lmpolygraph])
    }
)


def _make_handler(class_name: str) -> Any:
    """Build a closure that imports and runs the named estimator."""

    def _handle(payload: dict[str, Any]) -> dict[str, Any]:
        from lub import uncertainty
        from lub.wrappers.dummy import DummyBackend

        parsed = EstimatorInput.model_validate(payload)
        backend = DummyBackend(model_id=parsed.backend_model_id)
        cls = getattr(uncertainty, class_name)
        try:
            estimator = cls(**parsed.estimator_kwargs)
        except TypeError as exc:
            _LOG.warning("estimator.kwargs.invalid", estimator=class_name, error=str(exc))
            raise
        result = estimator.score(backend, parsed.prompt)
        out = EstimatorOutput(
            estimator=cls.REGISTRY_KEY,
            answer=str(result.answer),
            confidence=float(result.confidence),
            raw_scores={k: float(v) for k, v in result.raw_scores.items()},
            should_refuse=bool(result.should_refuse),
        )
        return out.model_dump()

    return _handle


def build_estimator_tools() -> list[ToolDef]:
    """Return one ToolDef per non-skipped public estimator class."""
    from lub import uncertainty
    from lub.mcp.server import ToolDef

    tools: list[ToolDef] = []
    for class_name in sorted(uncertainty.__all__):
        if class_name == "Estimator" or class_name in _SKIP:
            continue
        cls = getattr(uncertainty, class_name)
        registry_key = getattr(cls, "REGISTRY_KEY", "")
        if not registry_key:
            continue
        description = (cls.__doc__ or class_name).strip().splitlines()[0]
        tools.append(
            ToolDef(
                name=f"lub.estimator.{registry_key}",
                description=f"Run the {registry_key} estimator. {description}",
                input_model=EstimatorInput,
                output_model=EstimatorOutput,
                handler=_make_handler(class_name),
            )
        )
    return tools
