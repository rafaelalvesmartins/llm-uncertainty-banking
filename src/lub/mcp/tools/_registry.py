# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Auto-discovery + auto-wrap for estimators and metrics into MCP tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lub.mcp.tools.challenge import build_challenge_tools
from lub.mcp.tools.context_autopilot import build_context_autopilot_tools
from lub.mcp.tools.estimators import build_estimator_tools
from lub.mcp.tools.metrics import build_metric_tools
from lub.mcp.tools.plugin_loader import discover_plugins

if TYPE_CHECKING:
    from lub.mcp.server import ToolDef


def build_auto_tools() -> list[ToolDef]:
    """Return every auto-wrapped tool -- estimators, metrics, CEC, then ruflo plugins.

    Order matters: agents iterating the catalog generally prefer to see
    "score this prompt" tools before "evaluate this score sample"
    tools. Within each group the order is alphabetical by tool name.
    Discovered ruflo plugins come last so the catalog's lub-native
    primitives stay at the top of the list when plugins are present.

    The four ``lub.challenge.*`` tools (replay, explain_drift, report,
    meta_calibration_curve) sit between metrics and ruflo plugins --
    they are lub-native (so they precede plugins) but they are
    workflow-shaped (so they trail the per-estimator / per-metric
    primitives an agent would call first).
    """
    return [
        *build_estimator_tools(),
        *build_metric_tools(),
        *build_challenge_tools(),
        *build_context_autopilot_tools(),
        *discover_plugins(),
    ]
