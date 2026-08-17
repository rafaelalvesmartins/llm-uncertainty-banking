# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""lub.dashboard -- single-page web observability for CEC + ledger.

.. note::
   **Two dashboards in lub, by design.** This module
   (:mod:`lub.dashboard`) is the **live, in-process** observability
   surface: reads the ledger directly via a FastAPI app.
   The sibling :mod:`lub.reports.dashboard` is the **static,
   post-run** evidence viewer: composes finished JSON results into
   a single offline HTML file. Use this module for live monitoring;
   use :mod:`lub.reports.dashboard` for evidence packets that ship to
   auditors.

Per ADR-002, the dashboard positions LUB as the **calibrated-observability
layer** for ruflo-orchestrated agent swarms. Post pass-33 refactor, it is
also **decoupled from any single data source or output format** via two
Protocols:

* :class:`SnapshotSource` -- the data side. Default impl is
  :class:`LedgerSnapshotSource` (sqlite-backed); CSV/Prometheus/in-memory
  test doubles plug in symmetrically.
* :class:`SnapshotRenderer` -- the rendering side. Defaults are HTML and
  JSON; markdown / PDF / SVG plug in via :func:`register_renderer`.

Module map:

* :mod:`lub.dashboard.protocols`     -- Protocols + renderer registry
* :mod:`lub.dashboard.query`         -- generic ``build_snapshot(source, ...)``
* :mod:`lub.dashboard.ledger_source` -- default :class:`LedgerSnapshotSource`
* :mod:`lub.dashboard.render`        -- ``render_html`` / ``render_json``
                                        (auto-registered)
* :mod:`lub.dashboard.server`        -- ``build_app`` (generic) +
                                        ``build_app_from_ledger_path``
* :mod:`lub.dashboard.cli`           -- ``lub-dashboard render --ledger ...``

Spec: planning/29_Dashboard_Spec_2026-04-25.md.
"""

from __future__ import annotations

# Import render first so the default renderers register on package import.
from lub.dashboard import render as _render  # noqa: F401
from lub.dashboard.ledger_source import LedgerSnapshotSource
from lub.dashboard.protocols import (
    SnapshotRenderer,
    SnapshotSource,
    get_renderer,
    list_renderers,
    register_renderer,
)
from lub.dashboard.query import DashboardSnapshot, build_snapshot
from lub.dashboard.render import render_html, render_json
from lub.dashboard.server import (
    build_app,
    build_app_from_ledger_path,
    run_uvicorn,
)

__all__ = [
    # Data side
    "DashboardSnapshot",
    "build_snapshot",
    "SnapshotSource",
    "LedgerSnapshotSource",
    # Render side
    "render_html",
    "render_json",
    "SnapshotRenderer",
    "register_renderer",
    "get_renderer",
    "list_renderers",
    # Server side
    "build_app",
    "build_app_from_ledger_path",
    "run_uvicorn",
]
