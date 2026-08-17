# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for ``lub.mcp.tools.estimators`` — MCP auto-wrap of estimators."""

from __future__ import annotations

import pytest

from lub.mcp.tools import estimators as estimators_module
from lub.mcp.tools.estimators import _SKIP, _make_handler, build_estimator_tools

# ---------------------------------------------------------------------------
# Fakes — registered onto lub.uncertainty so the closure's late import
# resolves to our hermetic doubles. We never touch a real LLM backend.
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(
        self,
        confidence: float = 0.42,
        should_refuse: bool = False,
        raw: dict | None = None,
        answer: str = "fake-answer",
    ) -> None:
        self.answer = answer
        self.confidence = confidence
        self.raw_scores = raw if raw is not None else {"primary": 0.5, "secondary": 0.7}
        self.should_refuse = should_refuse


class _FakeEstimator:
    """Fake one-liner for tests."""

    REGISTRY_KEY = "fake_test_estimator"

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold

    def score(self, backend, prompt):  # noqa: ARG002 — banking-style ignored arg
        return _FakeResult()


class _ZeroConfEstimator:
    """Zero confidence edge case."""

    REGISTRY_KEY = "zero_conf_test"

    def __init__(self) -> None:
        pass

    def score(self, backend, prompt):  # noqa: ARG002
        return _FakeResult(confidence=0.0)


class _MaxConfEstimator:
    """Saturated confidence edge case."""

    REGISTRY_KEY = "max_conf_test"

    def __init__(self) -> None:
        pass

    def score(self, backend, prompt):  # noqa: ARG002
        return _FakeResult(confidence=1.0)


class _RefuseEstimator:
    """Always refuses — used to test guard signal propagation."""

    REGISTRY_KEY = "refuse_test"

    def __init__(self) -> None:
        pass

    def score(self, backend, prompt):  # noqa: ARG002
        return _FakeResult(confidence=0.99, should_refuse=True)


class _NoKwargEstimator:
    """Accepts no kwargs — used to verify TypeError surfacing."""

    REGISTRY_KEY = "no_kw_test"

    def __init__(self) -> None:
        pass

    def score(self, backend, prompt):  # noqa: ARG002
        return _FakeResult()


@pytest.fixture
def fake_estimators(monkeypatch):
    """Attach fake estimator classes onto the real ``lub.uncertainty`` module.

    The handler closure does ``from lub import uncertainty`` and then
    ``getattr(uncertainty, class_name)``, so registering attributes here
    is sufficient — no sys.modules surgery needed.
    """
    from lub import uncertainty as unc

    monkeypatch.setattr(unc, "_FakeEstimator", _FakeEstimator, raising=False)
    monkeypatch.setattr(unc, "_ZeroConfEstimator", _ZeroConfEstimator, raising=False)
    monkeypatch.setattr(unc, "_MaxConfEstimator", _MaxConfEstimator, raising=False)
    monkeypatch.setattr(unc, "_RefuseEstimator", _RefuseEstimator, raising=False)
    monkeypatch.setattr(unc, "_NoKwargEstimator", _NoKwargEstimator, raising=False)
    return unc


@pytest.fixture
def minimal_payload() -> dict:
    return {"prompt": "What is the APR on a 60-month auto loan?",
            "backend_model_id": "dummy",
            "estimator_kwargs": {}}


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


def test_public_api_only_exports_builder():
    assert estimators_module.__all__ == ["build_estimator_tools"]


def test_skip_set_is_frozen():
    assert isinstance(_SKIP, frozenset)


def test_skip_set_blocks_known_external_dep_estimators():
    """Estimators with heavy/optional deps must not be auto-wrapped."""
    expected = {
        "MCDropoutEstimator",
        "EigenScoreEstimator",
        "MahalanobisEstimator",
        "EnsembleEstimator",
        "LMPolygraphEstimator",
    }
    assert expected.issubset(_SKIP)


# ---------------------------------------------------------------------------
# _make_handler — handler closure behavior
# ---------------------------------------------------------------------------


def test_make_handler_returns_callable():
    assert callable(_make_handler("AnythingAtAll"))


def test_handler_runs_and_returns_valid_schema(fake_estimators, minimal_payload):
    handler = _make_handler("_FakeEstimator")
    payload = {**minimal_payload, "estimator_kwargs": {"threshold": 0.3}}
    out = handler(payload)

    assert out["estimator"] == "fake_test_estimator"
    assert out["answer"] == "fake-answer"
    assert isinstance(out["confidence"], float)
    assert 0.0 <= out["confidence"] <= 1.0
    assert isinstance(out["raw_scores"], dict)
    for value in out["raw_scores"].values():
        assert isinstance(value, float)
    assert out["should_refuse"] is False


def test_handler_zero_confidence_boundary(fake_estimators, minimal_payload):
    handler = _make_handler("_ZeroConfEstimator")
    out = handler(minimal_payload)
    assert out["confidence"] == 0.0
    assert 0.0 <= out["confidence"] <= 1.0


def test_handler_max_confidence_boundary(fake_estimators, minimal_payload):
    handler = _make_handler("_MaxConfEstimator")
    out = handler(minimal_payload)
    assert out["confidence"] == 1.0
    assert 0.0 <= out["confidence"] <= 1.0


def test_handler_refuse_flag_propagates(fake_estimators, minimal_payload):
    """Banking guardrail: should_refuse must surface verbatim — never silenced."""
    handler = _make_handler("_RefuseEstimator")
    out = handler(minimal_payload)
    assert out["should_refuse"] is True


def test_handler_does_not_refuse_when_estimator_does_not(fake_estimators, minimal_payload):
    handler = _make_handler("_FakeEstimator")
    out = handler(minimal_payload)
    assert out["should_refuse"] is False


def test_handler_raises_typeerror_on_unknown_kwarg(fake_estimators, minimal_payload):
    """Invalid kwargs must surface — silently swallowing breaks regulatory traceability."""
    handler = _make_handler("_NoKwargEstimator")
    bad_payload = {**minimal_payload, "estimator_kwargs": {"does_not_exist": 42}}
    with pytest.raises(TypeError):
        handler(bad_payload)


def test_handler_raises_attributeerror_for_unknown_class(fake_estimators, minimal_payload):
    handler = _make_handler("NonExistentEstimatorClass_xyz123")
    with pytest.raises(AttributeError):
        handler(minimal_payload)


def test_handler_invalid_payload_rejected(fake_estimators):
    """EstimatorInput.model_validate must reject malformed payloads."""
    handler = _make_handler("_FakeEstimator")
    with pytest.raises(Exception):  # noqa: BLE001 — pydantic ValidationError, type may vary
        handler({"prompt": None})  # missing required fields / wrong type


def test_handler_output_round_trips_through_model_dump(fake_estimators, minimal_payload):
    """Output must be a plain dict (JSON-serializable for MCP transport)."""
    handler = _make_handler("_FakeEstimator")
    out = handler(minimal_payload)
    assert isinstance(out, dict)
    # All values primitive enough to JSON-encode
    import json
    json.dumps(out)


# ---------------------------------------------------------------------------
# build_estimator_tools — discovery wiring
# ---------------------------------------------------------------------------


def test_build_estimator_tools_returns_list():
    tools = build_estimator_tools()
    assert isinstance(tools, list)


def test_build_estimator_tools_is_non_empty():
    """If this fails, lub.uncertainty has no auto-wrappable estimators — wiring broken."""
    tools = build_estimator_tools()
    assert len(tools) > 0


def test_build_estimator_tools_each_has_required_fields():
    for tool in build_estimator_tools():
        assert tool.name.startswith("lub.estimator.")
        assert len(tool.name) > len("lub.estimator.")
        assert tool.description
        assert callable(tool.handler)
        assert tool.input_model is not None
        assert tool.output_model is not None


def test_build_estimator_tools_excludes_skipped_classes():
    from lub import uncertainty

    skipped_tool_names = set()
    for class_name in _SKIP:
        cls = getattr(uncertainty, class_name, None)
        if cls is None:
            continue
        key = getattr(cls, "REGISTRY_KEY", None)
        if key:
            skipped_tool_names.add(f"lub.estimator.{key}")

    tool_names = {t.name for t in build_estimator_tools()}
    assert tool_names.isdisjoint(skipped_tool_names)


def test_build_estimator_tools_excludes_base_estimator():
    tool_names = {t.name for t in build_estimator_tools()}
    assert "lub.estimator." not in tool_names
    assert "lub.estimator.Estimator" not in tool_names


def test_build_estimator_tools_names_are_unique():
    tools = build_estimator_tools()
    names = [t.name for t in tools]
    assert len(names) == len(set(names)), "Duplicate MCP tool names would collide on registration"


def test_build_estimator_tools_description_is_single_line():
    """First line of docstring only — multi-line descriptions break some MCP clients."""
    for tool in build_estimator_tools():
        assert "\n" not in tool.description
