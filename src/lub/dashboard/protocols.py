# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""lub.dashboard.protocols -- decoupling surfaces for the dashboard.

Two Protocols define the dashboard's plug points so the rest of the
subpackage stays generic:

* :class:`SnapshotSource` -- anything that can answer the four KPI
  questions for a (start, end) window. The default implementation is
  :class:`~lub.dashboard.ledger_source.LedgerSnapshotSource` (sqlite-backed),
  but a CSV file, a Prometheus query, an in-memory test double, or a
  composite fan-out source can all satisfy this Protocol equally.

* :class:`SnapshotRenderer` -- anything that turns a
  :class:`~lub.dashboard.query.DashboardSnapshot` into bytes/text in some
  format. The defaults are HTML and JSON; markdown / PDF / SVG plug-ins
  can register without touching the core.

Spec: planning/29_Dashboard_Spec_2026-04-25.md sections 2-3 (post pass-33
refactor for genericity), planning/30_Generic_Architecture_Spec_2026-04-25.md
(the same Protocol-pluggability discipline applied earlier to benchmarks).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "SnapshotSource",
    "SnapshotRenderer",
    "register_renderer",
    "get_renderer",
    "list_renderers",
    "snapshot_renderer_registry_for_test",
]


@runtime_checkable
class SnapshotSource(Protocol):
    """Abstract data source for one dashboard snapshot.

    The four ``kpi_*`` methods are the minimum interface a source must
    expose. Each returns ``None`` (or an empty list / zero) when no data
    is available rather than raising -- the dashboard renders gracefully
    over empty sources.
    """

    def kpi_decisions(self, start: datetime, end: datetime) -> tuple[int, float]:
        """Return (decisions_in_window, abstention_rate)."""
        ...

    def kpi_outcomes(self, start: datetime, end: datetime) -> tuple[int, float | None]:
        """Return (n_outcomes_recorded, correctness_rate or None)."""
        ...

    def kpi_meta_calibration_ece(self) -> float | None:
        """Return binned ECE over recorded meta-calibration claims, or None."""
        ...

    def recent_decisions(
        self,
        start: datetime,
        end: datetime,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` recent decisions in window."""
        ...


@runtime_checkable
class SnapshotRenderer(Protocol):
    """A function that turns a snapshot into a string in some format.

    Renderers register themselves via :func:`register_renderer` so the
    CLI / server can resolve them by short name (``"html"``, ``"json"``,
    or any registered key).
    """

    content_type: str
    """MIME type the renderer produces (e.g. ``text/html``, ``application/json``)."""

    def __call__(self, snapshot: Any) -> str:
        """Render the snapshot to a string."""
        ...


# ---------------------------------------------------------------------------
# Renderer registry (additive, plug-in friendly)
# ---------------------------------------------------------------------------


_RENDERER_REGISTRY: dict[str, SnapshotRenderer] = {}


def register_renderer(name: str, renderer: SnapshotRenderer) -> None:
    """Register a renderer under a short name.

    Args:
        name: Short identifier (e.g. ``"html"``, ``"markdown"``).
        renderer: Anything satisfying :class:`SnapshotRenderer`.

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
    _RENDERER_REGISTRY[name] = renderer


def get_renderer(name: str) -> SnapshotRenderer:
    """Look up a registered renderer by name.

    Raises:
        KeyError: If no renderer is registered under ``name``.
    """
    try:
        return _RENDERER_REGISTRY[name]
    except KeyError as exc:
        known = sorted(_RENDERER_REGISTRY)
        raise KeyError(f"unknown renderer {name!r}; choose from {known}") from exc


def list_renderers() -> list[str]:
    """Return all registered renderer names, sorted."""
    return sorted(_RENDERER_REGISTRY)


def snapshot_renderer_registry_for_test() -> dict[str, SnapshotRenderer]:
    """Return a mutable view of the renderer registry for test save/restore.

    Tests should use this instead of touching the private
    ``_RENDERER_REGISTRY`` directly, e.g.::

        from lub.dashboard.protocols import snapshot_renderer_registry_for_test
        saved = dict(snapshot_renderer_registry_for_test())
        try:
            register_renderer("...", ...)
            ...
        finally:
            reg = snapshot_renderer_registry_for_test()
            reg.clear()
            reg.update(saved)
    """
    return _RENDERER_REGISTRY
