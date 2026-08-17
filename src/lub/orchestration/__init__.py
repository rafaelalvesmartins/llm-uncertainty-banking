# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Orchestration layer for llm-uncertainty-banking.

Ruflo-inspired building blocks that compose the existing estimators and
guards into higher-level uncertainty-aware runtimes:

* :class:`TieredRouter` -- cascaded inference across models, gated by UQ.
* :class:`UQSwarm` -- run several estimators in parallel and fuse scores
  (DAA-style consensus) producing a single calibrated confidence plus a
  ``method_disagreement`` second-order signal.
* :class:`HookedPipeline` -- pre/post hooks around ``pipeline.answer`` so
  the evidence store and ledger can live outside the hot path.

These modules depend only on stable public types from ``lub``; they do
not introduce new heavy dependencies.
"""

from __future__ import annotations

from lub.orchestration.hooks import (
    Hook,
    HookContext,
    HookedPipeline,
    HookRegistry,
)
from lub.orchestration.phases import Phase, PhaseConfig, active_phases
from lub.orchestration.router import (
    FailoverChain,
    FailoverExhausted,
    RouterResult,
    Tier,
    TieredRouter,
)
from lub.orchestration.router_protocol import (
    RouterPolicy,
    get_router_policy,
    list_router_policies,
    register_router_policy,
)
from lub.orchestration.swarm import SwarmResult, UQSwarm
from lub.orchestration.topology import (
    HierarchicalCoordinator,
    RoutingTable,
    SwarmTopology,
)

__all__ = [
    "FailoverChain",
    "FailoverExhausted",
    "HierarchicalCoordinator",
    "Hook",
    "HookContext",
    "HookRegistry",
    "HookedPipeline",
    "Phase",
    "PhaseConfig",
    "RouterPolicy",
    "RouterResult",
    "RoutingTable",
    "SwarmResult",
    "SwarmTopology",
    "Tier",
    "TieredRouter",
    "UQSwarm",
    "active_phases",
    "get_router_policy",
    "list_router_policies",
    "register_router_policy",
]
