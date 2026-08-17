# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Hierarchical mesh topology for swarm coordination.

Pattern 1 from ``planning/RUFLO_PATTERNS_TO_ADOPT_2026-04-25.md``.

Materializes a swarm topology as a routing table so a coordinator
agent can answer "to reach worker X from worker Y, who do I send to
next?" without peer-to-peer message broadcasting. Three topologies:

* :data:`SwarmTopology.HIERARCHICAL` — every cross-worker call goes
  through the coordinator.
* :data:`SwarmTopology.MESH` — every worker may call every worker
  directly (no coordinator routing).
* :data:`SwarmTopology.HYBRID` — workers within the same domain use
  mesh; cross-domain calls go through the coordinator's mesh links.

The implementation is intentionally framework-agnostic: agent
identifiers are plain strings, no LLM/UQ knowledge bleeds in. This is
infrastructure that the higher-level :mod:`lub.orchestration.swarm`
can consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SwarmTopology(StrEnum):
    """Coordination topology for a multi-agent swarm.

    String enum so it round-trips through TOML / JSON config.
    """

    HIERARCHICAL = "hierarchical"
    MESH = "mesh"
    HYBRID = "hybrid"


@dataclass(frozen=True)
class RoutingTable:
    """Materialized routing table for a swarm topology.

    Attributes
    ----------
    coordinator_id:
        Agent that owns the routing decisions for HIERARCHICAL /
        HYBRID topologies. Empty string when ``topology == MESH``.
    worker_ids:
        Tuple of worker identifiers. Order is preserved.
    cross_domain_links:
        For HYBRID only — explicit (worker_a, worker_b) pairs that
        bypass the coordinator. Tuple of tuples for hashability.
    """

    coordinator_id: str
    worker_ids: tuple[str, ...]
    cross_domain_links: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize sequence fields to tuples and validate cross-domain links."""
        if not isinstance(self.worker_ids, tuple):
            object.__setattr__(self, "worker_ids", tuple(self.worker_ids))
        if not isinstance(self.cross_domain_links, tuple):
            object.__setattr__(
                self,
                "cross_domain_links",
                tuple(tuple(p) for p in self.cross_domain_links),
            )
        # Sanity: cross-domain links reference known workers.
        known = set(self.worker_ids) | {self.coordinator_id} - {""}
        for a, b in self.cross_domain_links:
            if a not in known or b not in known:
                raise ValueError(
                    f"cross_domain_links references unknown worker(s): "
                    f"({a!r}, {b!r}); known: {sorted(known)}"
                )


class HierarchicalCoordinator:
    """Routes inter-agent messages according to a :class:`SwarmTopology`.

    Pure data + lookup; no I/O, no async, no LLM. Suitable for
    embedding in any orchestrator (lub's own swarm, an external
    framework via :class:`lub.agents.adapters.OrchestratorAgentProtocol`,
    or a future runtime).
    """

    def __init__(
        self,
        topology: SwarmTopology,
        routing_table: RoutingTable,
    ) -> None:
        """Bind the topology and precompute the symmetric cross-link set."""
        self._topology = topology
        self._table = routing_table
        self._cross_links: set[tuple[str, str]] = {
            (a, b) for a, b in routing_table.cross_domain_links
        } | {(b, a) for a, b in routing_table.cross_domain_links}

    @property
    def topology(self) -> SwarmTopology:
        """Return the configured swarm topology."""
        return self._topology

    @property
    def coordinator_id(self) -> str:
        """Return the coordinator agent identifier (empty string for MESH)."""
        return self._table.coordinator_id

    def route(self, from_agent: str, to_agent: str) -> str | None:
        """Return the next hop from ``from_agent`` to ``to_agent``.

        * Self-call (``from_agent == to_agent``): returns the agent
          itself (a degenerate route).
        * MESH: returns ``to_agent`` directly when both endpoints are
          known workers; ``None`` otherwise.
        * HIERARCHICAL: returns the coordinator if both endpoints are
          known workers; ``None`` otherwise. The coordinator itself
          can route to any worker directly.
        * HYBRID: same as HIERARCHICAL, except that an explicit
          ``cross_domain_links`` pair short-circuits the coordinator.
        """
        if from_agent == to_agent:
            return to_agent

        known_workers = set(self._table.worker_ids)
        coord = self._table.coordinator_id

        # In all topologies, the coordinator can talk to any worker
        # directly (no double-hop through itself).
        if from_agent == coord and to_agent in known_workers:
            return to_agent

        # If either endpoint is unknown, refuse.
        if from_agent not in known_workers and from_agent != coord:
            return None
        if to_agent not in known_workers and to_agent != coord:
            return None

        if self._topology is SwarmTopology.MESH:
            return to_agent

        if self._topology is SwarmTopology.HIERARCHICAL:
            return coord if coord else None

        # HYBRID
        if (from_agent, to_agent) in self._cross_links:
            return to_agent
        return coord if coord else None


__all__ = [
    "SwarmTopology",
    "RoutingTable",
    "HierarchicalCoordinator",
]
