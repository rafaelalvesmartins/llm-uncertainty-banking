"""
lub.runtime -- entry-point conventions for orchestration-core deployments.

Per ADR-002 (and its pass-25 generalization to any orchestrator
framework), an orchestration framework -- ruflo / langgraph / crewai /
autogen / etc. -- is the primary user-facing surface; LUB modules
provide calibrated workers running inside it. This subpackage codifies
the handshake.

The actual orchestrator runtime lives outside this Python package
(typically as a Node.js or sibling Python framework). ``lub.runtime``
does not import any specific orchestrator; it provides factory helpers
that build calibrated agents and expose them via
:func:`lub.agents.adapters.orchestrator.to_orchestrator_agent`.

Public surface (canonical, framework-agnostic):

- :class:`OrchestratedAgentSpec` (in :mod:`lub.runtime.engine`)
- :func:`build_calibrated_orchestrated_member`
- :func:`build_orchestrated_pack`
- :class:`SwarmConfig` (in :mod:`lub.runtime.swarm_config`) and friends
  for declarative swarm description.

Back-compat aliases (ruflo-flavored, see ADR-002 history):

- :class:`SwarmMemberSpec` (= :class:`OrchestratedAgentSpec`)
- :func:`build_calibrated_swarm_member`
- :func:`build_swarm_pack`

Both name sets resolve to the same objects. New code should prefer the
generic names.

See:

- :mod:`lub.runtime.engine` -- canonical generic implementation.
- :mod:`lub.runtime.ruflo_engine` -- back-compat shim re-exporting under
  ruflo names.
- :mod:`lub.runtime.swarm_config` -- declarative swarm configuration
  (pattern adapted with attribution from ruvnet/ruflo, MIT).
- :mod:`lub.agents.adapters.orchestrator` -- canonical Protocol-based bridge.
"""

from __future__ import annotations

from lub.runtime.engine import (
    ALLOWED_DOMAINS,
    OrchestratedAgentSpec,
    build_calibrated_orchestrated_member,
    build_orchestrated_pack,
    dispatch_by_domain,
)
from lub.runtime.swarm_config import (
    DomainConfig,
    LoadBalancingStrategy,
    LoggingConfig,
    LoggingFormat,
    LoggingLevel,
    LoggingOutput,
    PerformanceTargets,
    PhaseConfig,
    SwarmConfig,
    SwarmTopology,
)

# Back-compat aliases (pre-pass-25 names).
SwarmMemberSpec = OrchestratedAgentSpec
build_calibrated_swarm_member = build_calibrated_orchestrated_member
build_swarm_pack = build_orchestrated_pack

__all__ = [
    # Canonical generic factory primitives.
    "ALLOWED_DOMAINS",
    "OrchestratedAgentSpec",
    "build_calibrated_orchestrated_member",
    "build_orchestrated_pack",
    "dispatch_by_domain",
    # Declarative swarm configuration (pass 26).
    "SwarmConfig",
    "SwarmTopology",
    "LoadBalancingStrategy",
    "DomainConfig",
    "PhaseConfig",
    "PerformanceTargets",
    "LoggingConfig",
    "LoggingLevel",
    "LoggingFormat",
    "LoggingOutput",
    # Back-compat aliases.
    "SwarmMemberSpec",
    "build_calibrated_swarm_member",
    "build_swarm_pack",
]
