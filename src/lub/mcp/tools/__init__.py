# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Auto-generated MCP tool surface for lub estimators and metrics.

This subpackage discovers every public estimator (``lub.uncertainty``)
and a curated set of single-call metrics (``lub.calibration``) and
exposes each one as an individual MCP tool. The catalog ``build_server()``
composes at runtime:

* **5 hand-written workflow tools** in :mod:`lub.mcp.server` (score_with_p_true,
  score_with_token_sar, reliability_diagram, airmf_report, cascaded_answer).
* **17 estimator tools** auto-discovered from ``lub.uncertainty.__all__``
  (22 estimators - 5 in the documented skip list).
* **12 metric tools** auto-discovered from ``_METRIC_SPECS`` in
  :mod:`lub.mcp.tools.metrics`.
* **4 CEC tools** from :func:`build_challenge_tools` (``lub.challenge.replay``,
  ``explain_drift``, ``report``, ``meta_calibration_curve``).
* **N orchestrator-plugin tools** discovered on disk via
  :func:`lub.mcp.tools.plugin_loader.discover_plugins` from
  ``$LUB_PLUGINS_DIR`` / ``~/.lub/plugins/`` / ``./plugins/``. The
  loader's format-dispatch table (``PLUGIN_FORMAT_ADAPTERS``) ships
  the ruflo (``ruvnet/ruflo``) adapter built-in; further frameworks
  (langgraph, crewai, autogen) plug in via :func:`register_plugin_format`.

Total = 38 native tools out of the box, plus any installed plugins.

Public API:

* :func:`build_auto_tools` -- return the full list of auto-wrapped
  :class:`lub.mcp.server.ToolDef` objects, ready to be appended to
  :data:`lub.mcp.server.TOOLS`.
* :func:`build_challenge_tools` -- return only the 4 CEC tools (the
  v0.3 scaffold surface), exposed separately for callers who want it
  in isolation.
"""

from __future__ import annotations

from lub.mcp.tools._registry import build_auto_tools
from lub.mcp.tools.challenge import build_challenge_tools
from lub.mcp.tools.context_autopilot import build_context_autopilot_tools

__all__ = [
    "build_auto_tools",
    "build_challenge_tools",
    "build_context_autopilot_tools",
]
