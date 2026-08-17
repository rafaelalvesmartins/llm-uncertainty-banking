# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Auto-generate one MCP tool per single-call calibration metric.

Wraps the ``(confidences, correct) -> float`` family of metrics from
:mod:`lub.calibration.metrics` and :mod:`lub.calibration.scoring_rules`.
Metrics with non-uniform signatures (``compute_all``, ``analyze_drift``,
``reliability_curve`` which returns arrays) are NOT auto-wrapped — the
hand-written ``reliability_diagram`` tool in :mod:`lub.mcp.server`
already covers the array case.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog

from lub.mcp.schemas import MetricInput, MetricOutput

if TYPE_CHECKING:
    from lub.mcp.server import ToolDef


_LOG = structlog.get_logger(__name__)


# (tool_name, function_path, description)
_METRIC_SPECS: tuple[tuple[str, str, str], ...] = (
    (
        "ece",
        "lub.calibration.metrics:expected_calibration_error",
        "Expected Calibration Error — bin-weighted gap between confidence and accuracy.",
    ),
    (
        "rmsce",
        "lub.calibration.metrics:root_mean_squared_calibration_error",
        "Root-mean-squared calibration error across bins.",
    ),
    (
        "ence",
        "lub.calibration.metrics:expected_normalized_calibration_error",
        "Expected normalized calibration error (Nixon et al. 2019).",
    ),
    (
        "brier",
        "lub.calibration.metrics:brier_score",
        "Brier score — mean squared error between confidence and correctness.",
    ),
    (
        "refusal_auroc",
        "lub.calibration.metrics:refusal_auroc",
        "AUROC of confidence as a refusal signal vs ground-truth correctness.",
    ),
    (
        "sharpness",
        "lub.calibration.metrics:sharpness",
        "Sharpness — variance of the confidence distribution.",
    ),
    (
        "spearman_rho",
        "lub.calibration.metrics:spearman_rank_correlation",
        "Spearman's rho between confidence rank and correctness.",
    ),
    (
        "kendall_tau",
        "lub.calibration.metrics:kendall_tau",
        "Kendall's tau between confidence rank and correctness.",
    ),
    (
        "crps_from_confidence",
        "lub.calibration.scoring_rules:crps_from_confidence",
        "CRPS computed from a single confidence score against binary correctness.",
    ),
    (
        "nll",
        "lub.calibration.scoring_rules:negative_log_likelihood",
        "Negative log likelihood of correct outcomes under the confidence distribution.",
    ),
    ("auucc", "lub.calibration.ucc:auucc", "Area under the uncertainty-characteristics curve."),
    (
        "aurc",
        "lub.calibration.selective:area_under_risk_coverage",
        "Area under the risk-coverage curve (selective prediction).",
    ),
)


def _resolve(path: str) -> Callable[..., float]:
    module_path, attr = path.split(":", 1)
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, attr)  # type: ignore[no-any-return]


def _make_handler(name: str, fn_path: str) -> Any:
    def _handle(payload: dict[str, Any]) -> dict[str, Any]:
        parsed = MetricInput.model_validate(payload)
        fn = _resolve(fn_path)
        try:
            value = float(fn(parsed.confidences, parsed.correct, **parsed.metric_kwargs))
        except TypeError:
            # Some metrics (sharpness) take only confidences.
            value = float(fn(parsed.confidences, **parsed.metric_kwargs))
        except Exception as exc:  # pragma: no cover — defensive
            _LOG.warning("metric.error", metric=name, error=str(exc))
            raise
        # Description is the spec entry; keep it on the wire so agents
        # don't have to hold a separate catalog.
        description = next(d for n, _, d in _METRIC_SPECS if n == name)
        return MetricOutput(metric=name, value=value, description=description).model_dump()

    return _handle


def build_metric_tools() -> list[ToolDef]:
    """Return one ToolDef per spec entry in :data:`_METRIC_SPECS`."""
    from lub.mcp.server import ToolDef

    tools: list[ToolDef] = []
    for name, fn_path, description in _METRIC_SPECS:
        tools.append(
            ToolDef(
                name=f"lub.metric.{name}",
                description=description,
                input_model=MetricInput,
                output_model=MetricOutput,
                handler=_make_handler(name, fn_path),
            )
        )
    return tools
