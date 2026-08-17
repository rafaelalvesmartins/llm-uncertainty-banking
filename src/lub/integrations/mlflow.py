# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""MLflow integration for logging LUB artifacts to the Model Registry.

Banks standardize on MLflow for model risk management workflows.
This module provides a one-call API to log benchmark results, OSCAL
artifacts, and calibration metrics as MLflow run artifacts and metrics,
so MRM teams can track uncertainty alongside model performance in the
same registry they already use.

Usage::

    from lub.integrations.mlflow import log_benchmark_result

    # Inside an MLflow run:
    import mlflow
    with mlflow.start_run():
        log_benchmark_result(result)

Requires: ``pip install mlflow``
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from lub.guard import GuardResult
    from lub.types import BenchmarkResult

_LOG = structlog.get_logger("lub.integrations.mlflow")

_MISSING_MSG = "MLflow integration requires 'mlflow'. Install with: pip install mlflow"


def log_benchmark_result(
    result: BenchmarkResult,
    *,
    log_oscal: bool = True,
    log_assessment: bool = True,
    artifact_subdir: str = "lub",
) -> None:
    """Log a :class:`BenchmarkResult` to the active MLflow run.

    Logs:
    - All metrics from ``result.metrics`` as MLflow metrics
    - The full BenchmarkResult JSON as an artifact
    - OSCAL Component Definition JSON (if ``log_oscal=True``)
    - OSCAL Assessment Results JSON (if ``log_assessment=True``)

    Parameters
    ----------
    result:
        A completed benchmark result.
    log_oscal:
        Whether to log the OSCAL Component Definition.
    log_assessment:
        Whether to log the OSCAL Assessment Results (all 6 regimes).
    artifact_subdir:
        Subdirectory within the MLflow artifact store.
    """
    try:
        import mlflow
    except ImportError as exc:
        raise ImportError(_MISSING_MSG) from exc

    _LOG.info(
        "mlflow.log_start",
        backend=result.backend,
        estimator=result.estimator,
        dataset=result.dataset,
    )

    # Log metrics. The typed top-level fields (accuracy/ece/refusal_auroc)
    # are ALSO present in result.metrics (BenchmarkResult.metrics is
    # populated from compute_all() which includes them). Guard against
    # double-logging - MLflow silently overwrites the second value with
    # the same key, but emits a warning and the duplicate event wastes
    # tracking-server capacity at scale.
    logged: set[str] = set()
    for name, value in result.metrics.items():
        mlflow.log_metric(f"lub.{name}", value)
        logged.add(name)
    for fallback_name, fallback_value in (
        ("accuracy", result.accuracy),
        ("ece", result.ece),
        ("refusal_auroc", result.refusal_auroc),
    ):
        if fallback_name not in logged:
            mlflow.log_metric(f"lub.{fallback_name}", fallback_value)

    # Log tags
    mlflow.set_tag("lub.backend", result.backend)
    mlflow.set_tag("lub.estimator", result.estimator)
    mlflow.set_tag("lub.dataset", result.dataset)
    mlflow.set_tag("lub.repo_version", result.repo_version)
    if result.git_sha:
        mlflow.set_tag("lub.git_sha", result.git_sha)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # BenchmarkResult JSON
        result_path = tmp / "benchmark_result.json"
        result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        mlflow.log_artifact(str(result_path), artifact_subdir)

        # OSCAL Component Definition
        if log_oscal:
            from lub.reports.oscal import render_oscal_json

            oscal_path = tmp / "oscal_component_definition.json"
            oscal_path.write_text(render_oscal_json(result), encoding="utf-8")
            mlflow.log_artifact(str(oscal_path), artifact_subdir)

        # OSCAL Assessment Results
        if log_assessment:
            from lub.reports.assessment import render_assessment_json

            ar_path = tmp / "oscal_assessment_results.json"
            ar_path.write_text(render_assessment_json(result), encoding="utf-8")
            mlflow.log_artifact(str(ar_path), artifact_subdir)

    _LOG.info(
        "mlflow.log_done",
        n_metrics=len(result.metrics),
        oscal=log_oscal,
        assessment=log_assessment,
    )


def log_guard_result(
    prompt: str,
    guard_result: GuardResult,
    *,
    step: int | None = None,
) -> None:
    """Log a :class:`GuardResult` as MLflow metrics and tags.

    Parameters
    ----------
    prompt:
        The input prompt (logged as a tag, truncated to 250 chars).
    guard_result:
        A ``GuardResult`` from ``UncertaintyGuard.__call__()``.
    step:
        Optional MLflow step for time-series tracking.
    """
    try:
        import mlflow
    except ImportError as exc:
        raise ImportError(_MISSING_MSG) from exc

    mlflow.log_metric("lub.guard.confidence", guard_result.raw.confidence, step=step)
    mlflow.set_tag("lub.guard.decision", str(guard_result.outcome.decision))
    mlflow.set_tag("lub.guard.passed", str(guard_result.outcome.passed))
    mlflow.set_tag("lub.guard.prompt", prompt[:250])


__all__ = ["log_benchmark_result", "log_guard_result"]
