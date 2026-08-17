# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for lub.telemetry — OpenInference span attribute schema."""

from __future__ import annotations

from typing import Any

from lub.guard import UncertaintyGuard
from lub.telemetry import (
    span_attrs_for_estimator_score,
    span_attrs_for_guard_call,
    span_attrs_for_pipeline_call,
    traced,
)
from lub.types import UncertaintyResult


class _FakeBackend:
    REGISTRY_KEY = "fake"
    model_id = "fake-model-1"


class _FakeEstimator:
    REGISTRY_KEY = "fake_est"


class _FakePipeline:
    def __init__(self) -> None:
        self.backend = _FakeBackend()
        self.estimator = _FakeEstimator()
        self.refusal_threshold = 0.5

    def answer(self, prompt: str, **kwargs: Any) -> UncertaintyResult:
        return UncertaintyResult(answer="42", confidence=0.9, raw_scores={"agreement": 0.9})


def test_estimator_attrs_have_openinference_keys() -> None:
    result = UncertaintyResult(answer="42", confidence=0.85, raw_scores={"entropy": 0.3})
    attrs = span_attrs_for_estimator_score(
        _FakeEstimator(),  # type: ignore[arg-type]
        _FakeBackend(),  # type: ignore[arg-type]
        "What is the CET1 ratio?",
        result,
    )
    assert attrs["openinference.span.kind"] == "LLM"
    assert attrs["gen_ai.system"] == "lub"
    assert attrs["gen_ai.request.model"] == "fake-model-1"
    assert attrs["input.value"] == "What is the CET1 ratio?"
    assert attrs["output.value"] == "42"
    assert attrs["lub.estimator.name"] == "fake_est"
    assert attrs["lub.uncertainty.confidence"] == 0.85
    assert attrs["lub.uncertainty.should_refuse"] is False
    assert attrs["lub.backend"] == "fake"
    assert attrs["lub.raw_score.entropy"] == 0.3


def test_estimator_attrs_include_latency_when_provided() -> None:
    result = UncertaintyResult(answer="x", confidence=0.5)
    attrs = span_attrs_for_estimator_score(
        _FakeEstimator(),  # type: ignore[arg-type]
        _FakeBackend(),  # type: ignore[arg-type]
        "q",
        result,
        latency_ms=123.4,
    )
    assert attrs["lub.latency_ms"] == 123.4


def test_pipeline_attrs_span_kind_is_chain() -> None:
    pipe = _FakePipeline()
    result = pipe.answer("q")
    attrs = span_attrs_for_pipeline_call(pipe, "q", result)  # type: ignore[arg-type]
    assert attrs["openinference.span.kind"] == "CHAIN"
    assert attrs["lub.refusal_threshold"] == 0.5


def test_guard_attrs_span_kind_is_guard() -> None:
    pipe = _FakePipeline()
    guard = UncertaintyGuard(pipe, threshold=0.5)  # type: ignore[arg-type]
    guard_result = guard("q")
    attrs = span_attrs_for_guard_call(guard, "q", guard_result)  # type: ignore[arg-type]
    assert attrs["openinference.span.kind"] == "GUARD"
    assert attrs["lub.guard.decision"] == "passthrough"
    assert attrs["lub.guard.passed"] is True


def test_guard_attrs_failing_call() -> None:
    pipe = _FakePipeline()
    pipe.answer = lambda prompt, **kw: UncertaintyResult(answer="guess", confidence=0.1, raw_scores={})  # type: ignore[method-assign]
    guard = UncertaintyGuard(pipe, threshold=0.8)  # type: ignore[arg-type]
    guard_result = guard("q")
    attrs = span_attrs_for_guard_call(guard, "q", guard_result)  # type: ignore[arg-type]
    assert attrs["lub.guard.passed"] is False


def test_traced_records_latency() -> None:
    def fake_score(**kwargs: Any) -> UncertaintyResult:
        return UncertaintyResult(answer="ok", confidence=0.9)

    wrapped = traced(fake_score, span_name="test.score")
    result = wrapped()
    assert isinstance(result, UncertaintyResult)
    assert "otel_latency_ms" in result.diagnostics
    assert result.diagnostics["otel_latency_ms"] >= 0.0
    assert result.diagnostics["otel_span_name"] == "test.score"


def test_traced_preserves_function_name() -> None:
    def my_score() -> UncertaintyResult:
        return UncertaintyResult(answer="ok", confidence=0.5)

    wrapped = traced(my_score)
    assert wrapped.__name__ == "my_score"


def test_all_attr_values_are_otel_compatible_types() -> None:
    result = UncertaintyResult(answer="42", confidence=0.85, raw_scores={"x": 0.1})
    attrs = span_attrs_for_estimator_score(
        _FakeEstimator(),  # type: ignore[arg-type]
        _FakeBackend(),  # type: ignore[arg-type]
        "q",
        result,
    )
    for key, val in attrs.items():
        assert isinstance(key, str), f"key {key!r} is not str"
        assert isinstance(val, (str, float, bool, int)), f"value {val!r} for {key} is not an OTEL type"
