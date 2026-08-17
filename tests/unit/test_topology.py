# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Hermetic tests for ``lub.orchestration.topology`` (Pattern 1)."""

from __future__ import annotations

import pytest

from lub.orchestration.topology import (
    HierarchicalCoordinator,
    RoutingTable,
    SwarmTopology,
)

# ---------------------------------------------------------------------------
# SwarmTopology enum
# ---------------------------------------------------------------------------


def test_swarm_topology_values():
    assert SwarmTopology.HIERARCHICAL.value == "hierarchical"
    assert SwarmTopology.MESH.value == "mesh"
    assert SwarmTopology.HYBRID.value == "hybrid"


def test_swarm_topology_round_trips_through_string():
    # str-Enum, so casting both ways must work for config files.
    assert SwarmTopology("mesh") is SwarmTopology.MESH
    # SwarmTopology is a StrEnum, so str(member) returns the value, not the
    # qualified name. This is the contract that lets config files round-trip.
    assert str(SwarmTopology.HIERARCHICAL) == "hierarchical"


# ---------------------------------------------------------------------------
# RoutingTable
# ---------------------------------------------------------------------------


def test_routing_table_normalizes_lists_to_tuples():
    rt = RoutingTable(
        coordinator_id="coord",
        worker_ids=["a", "b", "c"],
        cross_domain_links=[("a", "b")],
    )
    assert isinstance(rt.worker_ids, tuple)
    assert isinstance(rt.cross_domain_links, tuple)
    assert isinstance(rt.cross_domain_links[0], tuple)


def test_routing_table_rejects_unknown_cross_link():
    with pytest.raises(ValueError, match="unknown worker"):
        RoutingTable(
            coordinator_id="coord",
            worker_ids=("a", "b"),
            cross_domain_links=(("a", "ghost"),),
        )


def test_routing_table_accepts_links_to_coordinator():
    # Coordinator is a known node for cross-link purposes.
    rt = RoutingTable(
        coordinator_id="coord",
        worker_ids=("a",),
        cross_domain_links=(("a", "coord"),),
    )
    assert ("a", "coord") in rt.cross_domain_links


def test_routing_table_empty_cross_domain_links_is_default():
    rt = RoutingTable(coordinator_id="c", worker_ids=("a",))
    assert rt.cross_domain_links == ()


# ---------------------------------------------------------------------------
# HierarchicalCoordinator routing
# ---------------------------------------------------------------------------


def _coord(topology: SwarmTopology, *, links=()) -> HierarchicalCoordinator:
    rt = RoutingTable(
        coordinator_id="coord",
        worker_ids=("a", "b", "c"),
        cross_domain_links=tuple(links),
    )
    return HierarchicalCoordinator(topology, rt)


def test_self_call_returns_self():
    c = _coord(SwarmTopology.MESH)
    assert c.route("a", "a") == "a"


def test_mesh_routes_directly():
    c = _coord(SwarmTopology.MESH)
    assert c.route("a", "b") == "b"
    assert c.route("a", "c") == "c"


def test_mesh_returns_none_for_unknown_endpoints():
    c = _coord(SwarmTopology.MESH)
    assert c.route("ghost", "a") is None
    assert c.route("a", "ghost") is None


def test_hierarchical_routes_through_coordinator():
    c = _coord(SwarmTopology.HIERARCHICAL)
    assert c.route("a", "b") == "coord"
    assert c.route("b", "c") == "coord"


def test_hierarchical_coordinator_can_reach_workers_directly():
    c = _coord(SwarmTopology.HIERARCHICAL)
    assert c.route("coord", "a") == "a"


def test_hybrid_uses_coordinator_by_default():
    c = _coord(SwarmTopology.HYBRID)
    assert c.route("a", "b") == "coord"


def test_hybrid_short_circuits_explicit_cross_link():
    c = _coord(SwarmTopology.HYBRID, links=[("a", "b")])
    assert c.route("a", "b") == "b"


def test_hybrid_cross_link_is_symmetric():
    # Spec says cross-domain links are bidirectional.
    c = _coord(SwarmTopology.HYBRID, links=[("a", "b")])
    assert c.route("b", "a") == "a"


def test_hybrid_unrelated_pair_still_uses_coordinator():
    c = _coord(SwarmTopology.HYBRID, links=[("a", "b")])
    # No cross-link a<->c, so routes via coord.
    assert c.route("a", "c") == "coord"


def test_topology_property_is_readable():
    c = _coord(SwarmTopology.HIERARCHICAL)
    assert c.topology is SwarmTopology.HIERARCHICAL
    assert c.coordinator_id == "coord"


def test_unknown_endpoint_short_circuits_in_hierarchical():
    c = _coord(SwarmTopology.HIERARCHICAL)
    assert c.route("a", "ghost") is None
    assert c.route("ghost", "a") is None
