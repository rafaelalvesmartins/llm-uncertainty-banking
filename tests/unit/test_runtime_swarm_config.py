# Copyright 2026 Rafael Martins Alves - Apache-2.0
"""Tests for ``lub.runtime.swarm_config``."""

from __future__ import annotations

import pytest

from lub.runtime.swarm_config import (
    DomainConfig,
    LoadBalancingStrategy,
    PerformanceTargets,
    PhaseConfig,
    SwarmConfig,
    SwarmTopology,
)

# ---------------------------------------------------------------------------
# Enum smokes
# ---------------------------------------------------------------------------


def test_swarm_topology_values():
    assert SwarmTopology.HIERARCHICAL.value == "hierarchical"
    assert SwarmTopology.MESH.value == "mesh"
    assert SwarmTopology.HYBRID.value == "hybrid"


def test_load_balancing_includes_lub_specific_strategy():
    """Confidence-weighted is the lub-specific addition."""
    assert LoadBalancingStrategy.CONFIDENCE_WEIGHTED.value == "confidence_weighted"


# ---------------------------------------------------------------------------
# DomainConfig
# ---------------------------------------------------------------------------


def test_domain_config_basic():
    d = DomainConfig(domain="risk", agents=("basel_reporter",), priority=1)
    assert d.domain == "risk"
    assert d.agents == ("basel_reporter",)
    assert d.priority == 1
    assert d.parallel_execution is True


def test_domain_config_rejects_empty_domain():
    with pytest.raises(ValueError, match="non-empty"):
        DomainConfig(domain="")


def test_domain_config_is_frozen():
    d = DomainConfig(domain="risk")
    with pytest.raises((AttributeError, TypeError)):
        d.domain = "compliance"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PhaseConfig
# ---------------------------------------------------------------------------


def test_phase_config_is_active_within_range():
    p = PhaseConfig(phase_id="p1", name="bootstrap", weeks=(1, 4))
    assert p.is_active(1) is True
    assert p.is_active(4) is True
    assert p.is_active(5) is False
    assert p.is_active(0) is False


def test_phase_config_rejects_inverted_weeks():
    with pytest.raises(ValueError, match="start <= end"):
        PhaseConfig(phase_id="p", name="x", weeks=(10, 5))


def test_phase_config_rejects_empty_id():
    with pytest.raises(ValueError, match="non-empty"):
        PhaseConfig(phase_id="", name="x", weeks=(1, 2))


# ---------------------------------------------------------------------------
# PerformanceTargets
# ---------------------------------------------------------------------------


def test_performance_targets_defaults():
    pt = PerformanceTargets()
    assert pt.max_ece == 0.10
    assert pt.min_refusal_auroc == 0.70
    assert pt.max_inference_p95_ms is None


def test_performance_targets_max_ece_bounds():
    with pytest.raises(ValueError, match="max_ece must be in"):
        PerformanceTargets(max_ece=1.5)
    with pytest.raises(ValueError, match="max_ece must be in"):
        PerformanceTargets(max_ece=-0.1)


def test_performance_targets_auroc_bounds():
    with pytest.raises(ValueError, match="min_refusal_auroc must be in"):
        PerformanceTargets(min_refusal_auroc=1.5)


# ---------------------------------------------------------------------------
# SwarmConfig top-level
# ---------------------------------------------------------------------------


def test_swarm_config_minimal():
    cfg = SwarmConfig(name="banking_v01")
    assert cfg.name == "banking_v01"
    assert cfg.topology == SwarmTopology.HIERARCHICAL
    assert cfg.load_balancing == LoadBalancingStrategy.CONFIDENCE_WEIGHTED


def test_swarm_config_rejects_empty_name():
    with pytest.raises(ValueError, match="non-empty"):
        SwarmConfig(name="")


def test_swarm_config_rejects_duplicate_domains():
    with pytest.raises(ValueError, match="Duplicate domain"):
        SwarmConfig(
            name="x",
            domains=(
                DomainConfig(domain="risk"),
                DomainConfig(domain="risk"),
            ),
        )


def test_swarm_config_rejects_duplicate_phase_ids():
    with pytest.raises(ValueError, match="Duplicate phase IDs"):
        SwarmConfig(
            name="x",
            phases=(
                PhaseConfig(phase_id="p", name="a", weeks=(1, 2)),
                PhaseConfig(phase_id="p", name="b", weeks=(3, 4)),
            ),
        )


def test_swarm_config_rejects_unknown_prerequisite():
    with pytest.raises(ValueError, match="unknown prerequisite"):
        SwarmConfig(
            name="x",
            phases=(
                PhaseConfig(
                    phase_id="p1", name="a", weeks=(1, 2),
                    prerequisites=("nonexistent",),
                ),
            ),
        )


# ---------------------------------------------------------------------------
# active_phases_at semantics
# ---------------------------------------------------------------------------


def test_active_phases_at_simple():
    p1 = PhaseConfig(phase_id="p1", name="bootstrap", weeks=(1, 4))
    p2 = PhaseConfig(
        phase_id="p2", name="rollout", weeks=(5, 12),
        prerequisites=("p1",),
    )
    cfg = SwarmConfig(name="x", phases=(p1, p2))

    # Mid-bootstrap: only p1 active.
    assert tuple(p.phase_id for p in cfg.active_phases_at(2)) == ("p1",)
    # After bootstrap, prerequisite met, p2 active.
    assert tuple(p.phase_id for p in cfg.active_phases_at(6)) == ("p2",)


def test_active_phases_at_blocks_when_prereq_not_complete():
    """If we ask about week 3 (still in p1), p2 has p1 as prereq but
    p1 has not ended yet -> p2 is not active."""
    p1 = PhaseConfig(phase_id="p1", name="bootstrap", weeks=(1, 4))
    p2 = PhaseConfig(
        phase_id="p2", name="overlap", weeks=(3, 6),
        prerequisites=("p1",),
    )
    cfg = SwarmConfig(name="x", phases=(p1, p2))
    active = cfg.active_phases_at(3)
    assert tuple(p.phase_id for p in active) == ("p1",)
