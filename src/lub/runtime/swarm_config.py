"""
lub.runtime.swarm_config -- declarative swarm configuration shape.

Pattern adapted with attribution from ``ruvnet/ruflo`` (MIT, npm
``claude-flow``). Code is original Python; only the data-shape (which
fields a swarm config carries) is inspired by ``swarm.config.ts`` in
the ruflo v3 source. No TypeScript code is copied.

The module gives you a way to describe a swarm declaratively before
materializing it via :func:`lub.runtime.engine.build_orchestrated_pack`:

- :class:`SwarmTopology` -- enum of supported topologies.
- :class:`LoadBalancingStrategy` -- enum of dispatching strategies.
- :class:`PerformanceTargets` -- numeric targets the swarm aims for.
- :class:`PhaseConfig` -- a temporal phase with ``[start_week, end_week]``
  and prerequisites.
- :class:`DomainConfig` -- a regulated-domain partition (risk,
  compliance, audit, ...) with priority and parallelism flags.
- :class:`SwarmConfig` -- the top-level container.

This is purely descriptive: it carries data, not behavior. The router
and topology implementations that consume these configs live in
:mod:`lub.orchestration` (already partially shipped).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "SwarmTopology",
    "LoadBalancingStrategy",
    "LoggingFormat",
    "LoggingLevel",
    "LoggingOutput",
    "DomainConfig",
    "PhaseConfig",
    "PerformanceTargets",
    "LoggingConfig",
    "SwarmConfig",
]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SwarmTopology(StrEnum):
    """Topology of the agent graph.

    HIERARCHICAL: leader/worker tree, fan-out capped at each level.
    MESH: full peer-to-peer mesh between agents.
    HYBRID: hierarchical between domains, mesh within each domain.
    """

    HIERARCHICAL = "hierarchical"
    MESH = "mesh"
    HYBRID = "hybrid"


class LoadBalancingStrategy(StrEnum):
    """How the router picks which agent to dispatch to."""

    ROUND_ROBIN = "round_robin"
    LEAST_BUSY = "least_busy"
    CAPABILITY_MATCH = "capability_match"
    CONFIDENCE_WEIGHTED = "confidence_weighted"  # lub-specific (uses UQ)


class LoggingLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class LoggingFormat(StrEnum):
    JSON = "json"
    PRETTY = "pretty"


class LoggingOutput(StrEnum):
    CONSOLE = "console"
    FILE = "file"
    BOTH = "both"


# ---------------------------------------------------------------------------
# Per-section configs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DomainConfig:
    """A regulated-domain partition of the swarm.

    Attributes:
        domain: Free-form domain tag (e.g. ``"risk"``, ``"compliance"``,
            ``"audit"``, ``"model_validation"``). Used by the router to
            filter agents by domain when dispatching.
        agents: Names of agents (matching ``OrchestratedAgentSpec.name``)
            that belong to this domain.
        priority: Ordering among domains (lower = earlier).
        parallel_execution: If True, the swarm may invoke this domain's
            agents in parallel; if False, calls within the domain are
            serialized.
    """

    domain: str
    agents: tuple[str, ...] = field(default_factory=tuple)
    priority: int = 100
    parallel_execution: bool = True

    def __post_init__(self) -> None:
        if not self.domain:
            raise ValueError("DomainConfig.domain must be a non-empty string")


@dataclass(frozen=True)
class PhaseConfig:
    """A temporal rollout phase.

    Attributes:
        phase_id: Stable identifier (e.g. ``"phase_1_bootstrap"``).
        name: Human-readable name.
        weeks: ``(start, end)`` inclusive, in absolute project weeks.
        active_domains: Domain tags active during this phase.
        prerequisites: Phase IDs that must be complete before this phase
            activates.
    """

    phase_id: str
    name: str
    weeks: tuple[int, int]
    active_domains: tuple[str, ...] = field(default_factory=tuple)
    prerequisites: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.phase_id:
            raise ValueError("PhaseConfig.phase_id must be a non-empty string")
        if len(self.weeks) != 2 or self.weeks[0] > self.weeks[1]:
            raise ValueError(
                f"PhaseConfig.weeks must be (start, end) with start <= end, got {self.weeks!r}"
            )

    def is_active(self, current_week: int) -> bool:
        """Return True if ``current_week`` falls within ``self.weeks``."""
        start, end = self.weeks
        return start <= current_week <= end


@dataclass(frozen=True)
class PerformanceTargets:
    """Numeric targets baked into the config.

    All fields are advisory; the swarm reports actuals on each run and
    the dashboard / report layer may flag misses.

    Attributes:
        max_ece: Upper bound on Expected Calibration Error.
        min_refusal_auroc: Lower bound on refusal-AUROC.
        max_inference_p95_ms: P95 inference latency upper bound (ms).
        max_memory_mb: P95 process memory ceiling (MB), if measured.
        startup_budget_ms: Cold-start budget (ms).
    """

    max_ece: float = 0.10
    min_refusal_auroc: float = 0.70
    max_inference_p95_ms: float | None = None
    max_memory_mb: float | None = None
    startup_budget_ms: float | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.max_ece <= 1.0:
            raise ValueError(f"max_ece must be in [0, 1], got {self.max_ece}")
        if not 0.0 <= self.min_refusal_auroc <= 1.0:
            raise ValueError(f"min_refusal_auroc must be in [0, 1], got {self.min_refusal_auroc}")


@dataclass(frozen=True)
class LoggingConfig:
    level: LoggingLevel = LoggingLevel.INFO
    format: LoggingFormat = LoggingFormat.JSON
    output: LoggingOutput = LoggingOutput.CONSOLE
    file_path: str | None = None


# ---------------------------------------------------------------------------
# Top-level container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SwarmConfig:
    """Top-level swarm configuration.

    Pattern adapted with attribution from ``ruvnet/ruflo`` (MIT). Code
    in this module is original Python; the data shape is inspired by
    ``v3/swarm.config.ts`` in the ruflo source tree.

    Attributes:
        name: Swarm name (e.g. ``"banking_compliance_v0_1"``).
        version: SemVer.
        description: Human-readable description.
        topology: Graph topology used by the router.
        load_balancing: Strategy used by the router.
        domains: Domain partitions.
        phases: Temporal rollout phases.
        performance: Performance targets.
        logging: Logging configuration.
        metadata: Free-form metadata attached to the config.
    """

    name: str
    version: str = "0.0.0"
    description: str = ""
    topology: SwarmTopology = SwarmTopology.HIERARCHICAL
    load_balancing: LoadBalancingStrategy = LoadBalancingStrategy.CONFIDENCE_WEIGHTED
    domains: tuple[DomainConfig, ...] = field(default_factory=tuple)
    phases: tuple[PhaseConfig, ...] = field(default_factory=tuple)
    performance: PerformanceTargets = field(default_factory=PerformanceTargets)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("SwarmConfig.name must be a non-empty string")
        # Domain names should be unique.
        domain_names = [d.domain for d in self.domains]
        if len(domain_names) != len(set(domain_names)):
            raise ValueError(f"Duplicate domain names in SwarmConfig: {domain_names}")
        # Phase IDs should be unique.
        phase_ids = [p.phase_id for p in self.phases]
        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError(f"Duplicate phase IDs in SwarmConfig: {phase_ids}")
        # Phase prerequisites must reference known phases.
        known = set(phase_ids)
        for p in self.phases:
            for prereq in p.prerequisites:
                if prereq not in known:
                    raise ValueError(
                        f"PhaseConfig {p.phase_id!r} references unknown prerequisite {prereq!r}"
                    )

    def active_phases_at(self, current_week: int) -> tuple[PhaseConfig, ...]:
        """Return phases active at ``current_week`` whose prerequisites
        are all complete (interpreted: prerequisite phase ended before
        ``current_week``).
        """
        completed = {p.phase_id for p in self.phases if p.weeks[1] < current_week}
        return tuple(
            p
            for p in self.phases
            if p.is_active(current_week) and all(prereq in completed for prereq in p.prerequisites)
        )
