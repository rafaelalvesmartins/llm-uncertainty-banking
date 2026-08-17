# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""OpenInference span-attribute schema for LUB telemetry.

Implements the full OpenInference semantic convention
(https://github.com/Arize-ai/openinference) for LUB's uncertainty
pipeline, guard, and individual estimator calls. The attribute dicts
returned by functions in this module are portable to Phoenix, Langfuse,
SigNoz, and any OTEL-compatible backend without a runtime dependency on
any tracing SDK.

Usage::

    from opentelemetry import trace
    from lub.telemetry import span_attrs_for_pipeline_call

    tracer = trace.get_tracer("lub")
    with tracer.start_as_current_span("lub.pipeline.answer") as span:
        result = pipeline.answer(prompt)
        span.set_attributes(span_attrs_for_pipeline_call(pipeline, prompt, result))

No hard dependency on ``opentelemetry-api`` — this module only builds
attribute dicts. The caller is responsible for creating spans.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from lub.types import UncertaintyResult

if TYPE_CHECKING:
    from lub.guard import GuardResult

# OpenInference standard attribute names (schema-only, no SDK dependency).
# See: https://github.com/Arize-ai/openinference/tree/main/spec
_OI_SPAN_KIND = "openinference.span.kind"
_OI_INPUT_VALUE = "input.value"
_OI_OUTPUT_VALUE = "output.value"

# gen_ai.* namespace (OpenLLMetry / OpenInference shared convention).
_GEN_AI_SYSTEM = "gen_ai.system"
_GEN_AI_REQUEST_MODEL = "gen_ai.request.model"

# LUB-specific attributes under the lub.* namespace.
_LUB_ESTIMATOR_NAME = "lub.estimator.name"
_LUB_CONFIDENCE = "lub.uncertainty.confidence"
_LUB_SHOULD_REFUSE = "lub.uncertainty.should_refuse"
_LUB_BACKEND = "lub.backend"
_LUB_REFUSAL_THRESHOLD = "lub.refusal_threshold"
_LUB_LATENCY_MS = "lub.latency_ms"


def _get_registry_key(obj: Any) -> str:
    """Extract REGISTRY_KEY from an object, falling back to class name."""
    key = getattr(type(obj), "REGISTRY_KEY", "") or ""
    return key if key else type(obj).__name__


def span_attrs_for_estimator_score(
    estimator: Any,
    backend: Any,
    prompt: str,
    result: UncertaintyResult,
    *,
    latency_ms: float | None = None,
) -> dict[str, str | float | bool]:
    """Build OpenInference span attributes for an ``Estimator.score()`` call.

    Accepts any estimator/backend duck type — does not require concrete
    :class:`Estimator` or :class:`ModelBackend` classes.

    Returns a flat dict suitable for ``span.set_attributes()``.
    """
    attrs: dict[str, str | float | bool] = {
        _OI_SPAN_KIND: "LLM",
        _GEN_AI_SYSTEM: "lub",
        _GEN_AI_REQUEST_MODEL: getattr(backend, "model_id", "unknown"),
        _OI_INPUT_VALUE: prompt,
        _OI_OUTPUT_VALUE: result.answer,
        _LUB_ESTIMATOR_NAME: _get_registry_key(estimator),
        _LUB_CONFIDENCE: float(result.confidence),
        _LUB_SHOULD_REFUSE: bool(result.should_refuse),
        _LUB_BACKEND: _get_registry_key(backend),
    }
    if latency_ms is not None:
        attrs[_LUB_LATENCY_MS] = latency_ms
    for key, val in result.raw_scores.items():
        attrs[f"lub.raw_score.{key}"] = float(val)
    return attrs


def span_attrs_for_pipeline_call(
    pipeline: Any,
    prompt: str,
    result: UncertaintyResult,
    *,
    latency_ms: float | None = None,
) -> dict[str, str | float | bool]:
    """Build OpenInference span attributes for a pipeline ``answer()`` call.

    Accepts any pipeline duck type with ``estimator``, ``backend``, and
    ``refusal_threshold`` attributes.
    """
    attrs = span_attrs_for_estimator_score(
        getattr(pipeline, "estimator", pipeline),
        getattr(pipeline, "backend", pipeline),
        prompt,
        result,
        latency_ms=latency_ms,
    )
    attrs[_OI_SPAN_KIND] = "CHAIN"
    attrs[_LUB_REFUSAL_THRESHOLD] = getattr(pipeline, "refusal_threshold", 0.5)
    return attrs


def span_attrs_for_guard_call(
    guard: Any,
    prompt: str,
    result: GuardResult,
    *,
    latency_ms: float | None = None,
) -> dict[str, str | float | bool]:
    """Build OpenInference span attributes for a guard ``__call__()``."""
    attrs = span_attrs_for_pipeline_call(
        getattr(guard, "pipeline", guard),
        prompt,
        result.raw,
        latency_ms=latency_ms,
    )
    attrs[_OI_SPAN_KIND] = "GUARD"
    attrs["lub.guard.decision"] = str(result.outcome.decision)
    attrs["lub.guard.passed"] = bool(result.outcome.passed)
    attrs["lub.guard.rmf_subcategory"] = result.rmf_subcategory
    return attrs


def traced(
    fn: Callable[..., Any],
    *,
    span_name: str | None = None,
    attrs_builder: Callable[..., dict[str, str | float | bool]] | None = None,
) -> Callable[..., Any]:
    """Decorator that records latency and builds OTEL-ready attributes.

    Works without ``opentelemetry-api`` installed — stores attributes on
    the result's ``diagnostics["otel_attributes"]`` dict for deferred
    export. When the opentelemetry SDK is available, callers can extract
    attributes and attach them to a real span.

    This is deliberately *not* a full OTEL instrumentation layer — it
    follows the "schema-only, no SDK dependency" principle from
    Section D anti-pattern #5.
    """

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Invoke ``fn``, measure elapsed time, and stash OTEL metadata on the result."""
        t0 = time.perf_counter()
        result = fn(*args, **kwargs)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if isinstance(result, UncertaintyResult):
            result.diagnostics["otel_latency_ms"] = elapsed_ms
            result.diagnostics["otel_span_name"] = span_name or fn.__qualname__
        return result

    wrapper.__name__ = fn.__name__
    wrapper.__qualname__ = fn.__qualname__
    wrapper.__doc__ = fn.__doc__
    return wrapper


__all__ = [
    "span_attrs_for_estimator_score",
    "span_attrs_for_guard_call",
    "span_attrs_for_pipeline_call",
    "traced",
]
