# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""Tests for lub.reports.dashboard_protocols."""

from __future__ import annotations

from typing import Any

import pytest

from lub.reports.dashboard_protocols import (
    EvidenceRenderer,
    EvidenceSource,
    evidence_renderer_registry_for_test,
    get_evidence_renderer,
    list_evidence_renderers,
    register_evidence_renderer,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Save and restore the renderer registry around each test."""
    registry = evidence_renderer_registry_for_test()
    saved = dict(registry)
    registry.clear()
    try:
        yield registry
    finally:
        registry.clear()
        registry.update(saved)


class _FakeRenderer:
    content_type = "text/html"

    def __call__(self, data: Any) -> str:
        return f"<html>{data}</html>"


class _FakeSource:
    def iter_benchmark_results(self):
        return [{"estimator": "e", "dataset": "d", "n": 1, "accuracy": 0.9, "ece": 0.01}]

    def iter_oscal_assessments(self):
        return [{"assessment-results": {"uuid": "x"}}]

    def iter_artefacts(self):
        return [{"name": "a.json", "kind": "benchmark"}]

    def regime_coverage(self):
        return [{"regime": "EU-AI-Act"}]

    def warnings(self):
        return ["minor warning"]


# ---------------------------------------------------------------------------
# Protocol structural checks
# ---------------------------------------------------------------------------


def test_evidence_source_protocol_recognizes_conforming_class():
    """A class implementing every method should pass isinstance check."""
    assert isinstance(_FakeSource(), EvidenceSource)


def test_evidence_source_protocol_rejects_non_conforming():
    """A bare object lacking the required methods must not pass the check."""

    class Empty:
        pass

    assert not isinstance(Empty(), EvidenceSource)


def test_evidence_renderer_protocol_recognizes_callable_with_content_type():
    """Callable with .content_type satisfies the EvidenceRenderer Protocol."""
    assert isinstance(_FakeRenderer(), EvidenceRenderer)


def test_evidence_renderer_protocol_rejects_callable_without_content_type():
    """A plain callable lacking content_type must not satisfy the Protocol."""

    def renderer(data: Any) -> str:
        return str(data)

    assert not isinstance(renderer, EvidenceRenderer)


# ---------------------------------------------------------------------------
# register_evidence_renderer
# ---------------------------------------------------------------------------


def test_register_evidence_renderer_stores_renderer():
    """A registered renderer is retrievable by name."""
    renderer = _FakeRenderer()
    register_evidence_renderer("html", renderer)
    assert get_evidence_renderer("html") is renderer


def test_register_evidence_renderer_rejects_empty_name():
    """Empty name must raise ValueError."""
    with pytest.raises(ValueError, match="non-empty"):
        register_evidence_renderer("", _FakeRenderer())


def test_register_evidence_renderer_rejects_non_callable():
    """Non-callable renderer must raise TypeError."""

    class NotCallable:
        content_type = "text/html"

    with pytest.raises(TypeError, match="callable"):
        register_evidence_renderer("bad", NotCallable())  # type: ignore[arg-type]


def test_register_evidence_renderer_rejects_missing_content_type():
    """Callable lacking content_type must raise TypeError."""

    def renderer(data: Any) -> str:
        return str(data)

    with pytest.raises(TypeError, match="content_type"):
        register_evidence_renderer("bad", renderer)  # type: ignore[arg-type]


def test_register_evidence_renderer_overwrites_existing_name():
    """Registering the same name twice replaces the previous renderer."""
    first = _FakeRenderer()
    second = _FakeRenderer()
    register_evidence_renderer("html", first)
    register_evidence_renderer("html", second)
    assert get_evidence_renderer("html") is second


# ---------------------------------------------------------------------------
# get_evidence_renderer
# ---------------------------------------------------------------------------


def test_get_evidence_renderer_unknown_raises_keyerror():
    """Unknown renderer name must raise KeyError citing known choices."""
    register_evidence_renderer("html", _FakeRenderer())
    with pytest.raises(KeyError, match="unknown evidence renderer"):
        get_evidence_renderer("nonexistent")


def test_get_evidence_renderer_returns_callable_producing_string():
    """The returned renderer should be callable and produce a string."""
    register_evidence_renderer("html", _FakeRenderer())
    renderer = get_evidence_renderer("html")
    out = renderer("payload")
    assert isinstance(out, str)
    assert "payload" in out


# ---------------------------------------------------------------------------
# list_evidence_renderers
# ---------------------------------------------------------------------------


def test_list_evidence_renderers_empty_when_no_registrations():
    """Empty registry should return an empty list."""
    assert list_evidence_renderers() == []


def test_list_evidence_renderers_returns_sorted_names():
    """Listing should return registered names in sorted order."""
    register_evidence_renderer("html", _FakeRenderer())
    register_evidence_renderer("markdown", _FakeRenderer())
    register_evidence_renderer("pdf", _FakeRenderer())
    assert list_evidence_renderers() == ["html", "markdown", "pdf"]


# ---------------------------------------------------------------------------
# evidence_renderer_registry_for_test
# ---------------------------------------------------------------------------


def test_evidence_renderer_registry_for_test_is_mutable_view():
    """The returned dict should be the live registry, supporting save/restore."""
    registry = evidence_renderer_registry_for_test()
    register_evidence_renderer("html", _FakeRenderer())
    assert "html" in registry
    registry.clear()
    assert list_evidence_renderers() == []
