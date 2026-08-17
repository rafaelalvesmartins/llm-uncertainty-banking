# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""lub.reports.dashboard_protocols -- decoupling surfaces for the static dashboard.

Mirrors the Protocol-pluggability discipline from :mod:`lub.dashboard.protocols`
(applied to the live dashboard in pass 33) on the **static** evidence
dashboard side. Two Protocols define the plug points:

* :class:`EvidenceSource` -- anything that can iterate finished evaluation
  artefacts (BenchmarkResult JSONs, OSCAL Assessment-Results JSONs, plus
  a regulatory regime catalog). The default implementation is
  :class:`~lub.reports.dashboard_sources.DirEvidenceSource` (filesystem
  walk over a directory of JSONs); future plug-ins can read from S3, a
  ZIP file, a Git artefact bundle, or an in-memory test fixture.

* :class:`EvidenceRenderer` -- anything that turns a
  :class:`~lub.reports.dashboard.DashboardData` into a string in some
  format. The default is HTML (``render_dashboard_html``); markdown, PDF,
  or plain-text plug-ins can register without touching the core.

Spec: planning/29_Dashboard_Spec_2026-04-25.md (post pass-34 refactor),
planning/30_Generic_Architecture_Spec_2026-04-25.md (the same
Protocol-pluggability discipline applied to benchmarks and the live
dashboard).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "EvidenceSource",
    "EvidenceRenderer",
    "register_evidence_renderer",
    "get_evidence_renderer",
    "list_evidence_renderers",
    "evidence_renderer_registry_for_test",
]


@runtime_checkable
class EvidenceSource(Protocol):
    """Abstract source of finished evaluation artefacts.

    Each method returns an iterable (or list) of payloads / catalog rows.
    Empty iterables are valid -- the dashboard renders gracefully over an
    empty source.
    """

    def iter_benchmark_results(self) -> Iterable[dict[str, Any]]:
        """Yield BenchmarkResult-shaped dicts (estimator/dataset/n/accuracy/ece)."""
        ...

    def iter_oscal_assessments(self) -> Iterable[dict[str, Any]]:
        """Yield OSCAL Assessment-Results-shaped dicts (key 'assessment-results')."""
        ...

    def iter_artefacts(self) -> Iterable[dict[str, str]]:
        """Yield catalog rows: dicts with at least 'name' and 'kind' keys."""
        ...

    def regime_coverage(self) -> list[dict[str, Any]]:
        """Return regulatory regime catalog rows; empty list when unavailable."""
        ...

    def warnings(self) -> list[str]:
        """Return non-fatal warnings raised while collecting artefacts."""
        ...


@runtime_checkable
class EvidenceRenderer(Protocol):
    """A function that turns a :class:`DashboardData` into a string.

    Renderers register themselves via :func:`register_evidence_renderer`
    so callers can resolve them by short name (``"html"``, or any plug-in
    key like ``"markdown"``, ``"pdf"``).
    """

    content_type: str
    """MIME type the renderer produces (e.g. ``text/html``, ``text/markdown``)."""

    def __call__(self, data: Any) -> str:
        """Render the DashboardData to a string."""
        ...


# ---------------------------------------------------------------------------
# Renderer registry (additive, plug-in friendly)
# ---------------------------------------------------------------------------


_EVIDENCE_RENDERER_REGISTRY: dict[str, EvidenceRenderer] = {}


def register_evidence_renderer(name: str, renderer: EvidenceRenderer) -> None:
    """Register an evidence-dashboard renderer under a short name.

    Args:
        name: Short identifier (e.g. ``"html"``, ``"markdown"``).
        renderer: Anything satisfying :class:`EvidenceRenderer`.

    Raises:
        ValueError: If ``name`` is empty.
        TypeError: If ``renderer`` lacks ``content_type`` or is not callable.
    """
    if not name:
        raise ValueError("name must be a non-empty string")
    if not callable(renderer) or not hasattr(renderer, "content_type"):
        raise TypeError(
            f"renderer must be callable and expose .content_type (got {type(renderer).__name__})"
        )
    _EVIDENCE_RENDERER_REGISTRY[name] = renderer


def get_evidence_renderer(name: str) -> EvidenceRenderer:
    """Look up a registered evidence renderer by name.

    Raises:
        KeyError: If no renderer is registered under ``name``.
    """
    try:
        return _EVIDENCE_RENDERER_REGISTRY[name]
    except KeyError as exc:
        known = sorted(_EVIDENCE_RENDERER_REGISTRY)
        raise KeyError(f"unknown evidence renderer {name!r}; choose from {known}") from exc


def list_evidence_renderers() -> list[str]:
    """Return all registered evidence-renderer names, sorted."""
    return sorted(_EVIDENCE_RENDERER_REGISTRY)


def evidence_renderer_registry_for_test() -> dict[str, EvidenceRenderer]:
    """Return a mutable view of the evidence-renderer registry for test save/restore.

    Tests should use this instead of touching the private
    ``_EVIDENCE_RENDERER_REGISTRY`` directly.
    """
    return _EVIDENCE_RENDERER_REGISTRY
