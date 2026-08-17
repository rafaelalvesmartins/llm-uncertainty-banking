# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""Tests for the pass-34 refactor of lub.reports.dashboard.

Mirrors the pass-33 tests for lub.dashboard. Covers:

1. EvidenceSource + EvidenceRenderer Protocols are runtime-checkable.
2. DirEvidenceSource (default) walks a directory and classifies JSONs.
3. InMemoryEvidenceSource (canonical plug-in reference) works without
   inheritance.
4. collect_dashboard_data accepts EvidenceSource OR a Path (back-compat shim).
5. build_dashboard with format='html' (default) and format='markdown'
   (registered plug-in renderer) both work.

Spec: planning/29_Dashboard_Spec_2026-04-25.md (post pass-34 refactor).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


def test_evidence_source_protocol_exists():
    from lub.reports.dashboard_protocols import EvidenceSource
    assert EvidenceSource is not None


def test_evidence_renderer_protocol_exists():
    from lub.reports.dashboard_protocols import EvidenceRenderer
    assert EvidenceRenderer is not None


def test_html_renderer_auto_registers():
    """Importing lub.reports.dashboard must auto-register the html renderer."""
    from lub.reports import dashboard  # noqa: F401 -- side effect
    from lub.reports.dashboard_protocols import (
        get_evidence_renderer,
        list_evidence_renderers,
    )
    assert "html" in list_evidence_renderers()
    assert get_evidence_renderer("html").content_type == "text/html"


# ---------------------------------------------------------------------------
# DirEvidenceSource (default)
# ---------------------------------------------------------------------------


def test_dir_evidence_source_walks_directory(tmp_path):
    from lub.reports.dashboard_protocols import EvidenceSource
    from lub.reports.dashboard_sources import DirEvidenceSource

    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "p_true_finqa.json").write_text(json.dumps({
        "estimator": "p_true", "backend": "openai", "dataset": "finqa",
        "n": 100, "accuracy": 0.85, "ece": 0.04,
    }))
    (results_dir / "oscal.json").write_text(json.dumps({
        "assessment-results": {"results": [{"findings": []}]}
    }))
    (results_dir / "garbage.txt.json").write_text("not json")

    src = DirEvidenceSource(results_dir)
    assert isinstance(src, EvidenceSource)
    benches = list(src.iter_benchmark_results())
    oscals = list(src.iter_oscal_assessments())
    arts = list(src.iter_artefacts())
    warns = src.warnings()

    assert len(benches) == 1 and benches[0]["estimator"] == "p_true"
    assert len(oscals) == 1
    assert len(arts) == 2  # garbage skipped
    assert any("garbage.txt.json" in w for w in warns)


def test_dir_evidence_source_handles_missing_dir(tmp_path):
    from lub.reports.dashboard_sources import DirEvidenceSource
    src = DirEvidenceSource(tmp_path / "nonexistent")
    assert list(src.iter_benchmark_results()) == []
    assert any("does not exist" in w for w in src.warnings())


# ---------------------------------------------------------------------------
# InMemoryEvidenceSource (plug-in reference)
# ---------------------------------------------------------------------------


def test_in_memory_evidence_source_satisfies_protocol():
    from lub.reports.dashboard_protocols import EvidenceSource
    from lub.reports.dashboard_sources import InMemoryEvidenceSource
    src = InMemoryEvidenceSource(
        benchmark_results=[{"estimator": "x", "dataset": "y", "n": 1,
                            "accuracy": 1.0, "ece": 0.01}],
    )
    assert isinstance(src, EvidenceSource)
    assert len(list(src.iter_benchmark_results())) == 1


def test_custom_plugin_evidence_source_works():
    """A duck-typed source with no inheritance must be accepted."""
    from lub.reports.dashboard import collect_dashboard_data
    from lub.reports.dashboard_protocols import EvidenceSource

    class S3StubSource:
        def iter_benchmark_results(self):
            return [{"estimator": "stub", "dataset": "stub", "n": 1,
                     "accuracy": 1.0, "ece": 0.01}]
        def iter_oscal_assessments(self): return []
        def iter_artefacts(self): return [{"name": "s3://k/x.json", "kind": "benchmark"}]
        def regime_coverage(self): return []
        def warnings(self): return []

    src = S3StubSource()
    assert isinstance(src, EvidenceSource)
    data = collect_dashboard_data(src)
    assert data.estimator_rows[0]["estimator"] == "stub"
    assert data.artefacts[0]["name"].startswith("s3://")


# ---------------------------------------------------------------------------
# collect_dashboard_data + build_dashboard back-compat
# ---------------------------------------------------------------------------


def test_collect_dashboard_data_back_compat_with_path(tmp_path):
    """Legacy callers passing a Path keep working via the shim."""
    from lub.reports.dashboard import collect_dashboard_data
    results_dir = tmp_path / "r"
    results_dir.mkdir()
    (results_dir / "x.json").write_text(json.dumps({
        "estimator": "p_true", "backend": "openai", "dataset": "finqa",
        "n": 100, "accuracy": 0.85, "ece": 0.04,
    }))
    data = collect_dashboard_data(results_dir, title="bc")
    assert data.title == "bc"
    assert any(r["estimator"] == "p_true" for r in data.estimator_rows)


def test_build_dashboard_back_compat_with_path(tmp_path):
    from lub.reports.dashboard import build_dashboard
    results_dir = tmp_path / "r"
    results_dir.mkdir()
    (results_dir / "x.json").write_text(json.dumps({
        "estimator": "p_true", "backend": "openai", "dataset": "finqa",
        "n": 100, "accuracy": 0.85, "ece": 0.04,
    }))
    out = tmp_path / "d.html"
    build_dashboard(results_dir, out, title="bc")
    body = out.read_text()
    assert "bc" in body
    assert "p_true" in body


def test_build_dashboard_with_explicit_source(tmp_path):
    from lub.reports.dashboard import build_dashboard
    from lub.reports.dashboard_sources import InMemoryEvidenceSource
    src = InMemoryEvidenceSource(benchmark_results=[{
        "estimator": "se", "backend": "anthropic", "dataset": "convfinqa",
        "n": 200, "accuracy": 0.91, "ece": 0.03,
    }])
    out = tmp_path / "d.html"
    build_dashboard(src, out, title="explicit")
    body = out.read_text()
    assert "explicit" in body and "se" in body


def test_collect_unknown_source_returns_empty_with_warning():
    from lub.reports.dashboard import collect_dashboard_data
    data = collect_dashboard_data(object(), title="bad")
    assert data.estimator_rows == []
    assert any("unrecognised" in w.lower() for w in data.warnings)


# ---------------------------------------------------------------------------
# Renderer registry
# ---------------------------------------------------------------------------


def test_register_custom_renderer_then_use_it():
    from lub.reports import dashboard  # noqa: F401 -- ensures html renderer registered
    from lub.reports.dashboard import DashboardData
    from lub.reports.dashboard_protocols import (
        evidence_renderer_registry_for_test,
        get_evidence_renderer,
        list_evidence_renderers,
        register_evidence_renderer,
    )

    _EVIDENCE_RENDERER_REGISTRY = evidence_renderer_registry_for_test()

    saved = dict(_EVIDENCE_RENDERER_REGISTRY)
    try:
        def render_text(data: Any) -> str:
            return f"runs={len(data.estimator_rows)}"
        render_text.content_type = "text/plain"

        register_evidence_renderer("text", render_text)
        assert "text" in list_evidence_renderers()
        d = DashboardData(title="t", generated_at="now")
        assert get_evidence_renderer("text")(d) == "runs=0"
    finally:
        _EVIDENCE_RENDERER_REGISTRY.clear()
        _EVIDENCE_RENDERER_REGISTRY.update(saved)


def test_build_dashboard_with_format_argument(tmp_path):
    """build_dashboard(format='X') must use the X-registered renderer."""
    from lub.reports.dashboard import build_dashboard
    from lub.reports.dashboard_protocols import (
        evidence_renderer_registry_for_test,
        register_evidence_renderer,
    )

    _EVIDENCE_RENDERER_REGISTRY = evidence_renderer_registry_for_test()
    from lub.reports.dashboard_sources import InMemoryEvidenceSource

    saved = dict(_EVIDENCE_RENDERER_REGISTRY)
    try:
        def render_md(data: Any) -> str:
            return f"# {data.title}\n\nruns: {len(data.estimator_rows)}\n"
        render_md.content_type = "text/markdown"
        register_evidence_renderer("markdown", render_md)

        src = InMemoryEvidenceSource()
        out = tmp_path / "d.md"
        build_dashboard(src, out, title="md test", format="markdown")
        assert out.read_text().startswith("# md test")
    finally:
        _EVIDENCE_RENDERER_REGISTRY.clear()
        _EVIDENCE_RENDERER_REGISTRY.update(saved)


def test_register_evidence_renderer_rejects_empty_name():
    from lub.reports.dashboard_protocols import register_evidence_renderer
    def r(d): return "x"
    r.content_type = "text/plain"
    with pytest.raises(ValueError, match="non-empty"):
        register_evidence_renderer("", r)


def test_register_evidence_renderer_rejects_non_callable():
    from lub.reports.dashboard_protocols import register_evidence_renderer
    with pytest.raises(TypeError, match="callable"):
        register_evidence_renderer("bad", "not callable")  # type: ignore[arg-type]


def test_get_evidence_renderer_raises_for_unknown():
    from lub.reports.dashboard_protocols import get_evidence_renderer
    with pytest.raises(KeyError, match="nonexistent"):
        get_evidence_renderer("nonexistent")
