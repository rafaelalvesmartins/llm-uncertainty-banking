"""
lub.runtime.engine -- factory helpers for orchestration-core deployments.

Per ADR-002 (and its pass-25 generalization to any orchestrator
framework), the recommended user-facing entry point for LUB is **not**
to build a :class:`~lub.pipeline.UncertaintyPipeline` directly, but to
build calibrated agents and hand them to an **orchestration framework**
(ruflo, langgraph, crewai, autogen, ...). This module provides the
factory helpers that produce orchestrator-shaped agents from LUB
primitives.

Pass-26.6 refactor: ``OrchestratedAgentSpec.description`` now defaults
to ``None`` (ergonomic improvement); a new optional ``metadata`` field
lets callers carry arbitrary key/value annotations to the orchestrator
side without misusing ``tags``. ``CalibratedAgent`` is imported under
:data:`typing.TYPE_CHECKING` since it is only referenced in a type
alias.

Important: this module does **not** import any specific orchestrator.
The orchestrator runtime lives outside Python (or in a sibling Python
framework). Bridging is the consumer's responsibility -- typically
through a JSON-RPC subprocess, an MCP plugin loader, or the
framework's native Python API.

Example::

    from lub.agents import CalibratedAgent
    from lub.runtime import build_orchestrated_pack, OrchestratedAgentSpec
    from lub.uncertainty import SemanticEntropy
    from lub.agents.policies import RefusalPolicy

    class BaselReporter(CalibratedAgent):
        prompt_template = "Answer this Basel III question: {q}"
        def parse(self, raw: str) -> str:
            return raw.strip()

    pack = build_orchestrated_pack([
        OrchestratedAgentSpec(
            name="basel_reporter",
            description="Basel III Pillar 3 reporter",
            agent_factory=lambda: BaselReporter(
                backend=my_backend,
                uncertainty=SemanticEntropy(my_backend),
                policy=RefusalPolicy(threshold=0.7),
            ),
            tags=("regulatory", "basel-iii"),
            metadata={"owner": "mrm-team", "sla_p95_ms": 800},
        ),
        # ... more members ...
    ])
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from lub.agents.adapters.orchestrator import (
    OrchestratorAgentProtocol,
    to_orchestrator_agent,
)
from lub.protocols import AuditKey

if TYPE_CHECKING:  # avoid runtime import; only needed for the type alias.
    from lub.agents.core import CalibratedAgent

__all__ = [
    "ALLOWED_DOMAINS",
    "OrchestratedAgentSpec",
    "build_calibrated_orchestrated_member",
    "build_orchestrated_pack",
    "dispatch_by_domain",
]


# Type alias for the factory callable; distinguishes "factory of a
# CalibratedAgent" from any other factory.
AgentFactory = Callable[[], "CalibratedAgent[Any, Any]"]


# Read-only empty mapping used as the default for OrchestratedAgentSpec.metadata.
# Using MappingProxyType keeps the frozen dataclass actually immutable
# (a plain ``dict`` default would be a mutable shared reference, even
# inside a "frozen" dataclass).
_EMPTY_METADATA: Mapping[str, Any] = MappingProxyType({})


# Pattern 2 (spec 30): banking-domain partition for orchestrator dispatch.
# Frozen so callers cannot accidentally extend it at runtime — domains
# define the audit-defensible routing boundary and adding one is a
# deliberate v0.x surface decision.
ALLOWED_DOMAINS: frozenset[str] = frozenset({"risk", "compliance", "audit", "model_validation"})


@dataclass(frozen=True)
class OrchestratedAgentSpec:
    """Declarative spec for one calibrated agent in an orchestration pack.

    Attributes:
        name: Unique name within the target orchestrator.
        agent_factory: Zero-argument callable returning a fully configured
            :class:`~lub.agents.core.CalibratedAgent`. Wrapping in a
            factory (instead of passing the agent directly) lets the
            orchestrator construct agents lazily, one per worker
            process, which matters when a backend opens GPU sessions
            or HTTP connections.
        description: Optional human-readable description recorded on
            the orchestrator-shaped agent. Defaults to ``None``.
        tags: Optional metadata tags surfaced to the orchestrator router
            (e.g. ``("regulatory", "basel-iii")``). Tags are strings
            for routing; richer metadata goes in ``metadata`` instead.
        metadata: Optional mapping of free-form key/value annotations
            propagated to the orchestrator-shaped agent's ``metadata``
            dict at materialization time. Defaults to an empty
            read-only mapping.
        domain: Banking-domain partition for orchestrator dispatch
            (Pattern 2 from :doc:`planning/30_Generic_Architecture_Spec`).
            Must be one of :data:`ALLOWED_DOMAINS`. Defaults to
            ``"compliance"``.
        priority: Higher-priority specs are dispatched first within a
            domain (see :func:`dispatch_by_domain`). Ties broken by
            ``name`` lexicographically. Defaults to ``0``.
        parallel_safe: Whether the orchestrator may run this agent in
            parallel with siblings from the same domain. Defaults to
            ``False`` (sequential is the audit-defensible default).
    """

    name: str
    agent_factory: AgentFactory
    description: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = _EMPTY_METADATA
    domain: str = "compliance"
    priority: int = 0
    parallel_safe: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("OrchestratedAgentSpec.name must be a non-empty string")
        if not callable(self.agent_factory):
            raise TypeError(
                f"agent_factory must be callable, got {type(self.agent_factory).__name__}"
            )
        if self.domain not in ALLOWED_DOMAINS:
            raise ValueError(
                f"OrchestratedAgentSpec.domain must be one of "
                f"{sorted(ALLOWED_DOMAINS)}; got {self.domain!r}"
            )


def build_calibrated_orchestrated_member(
    spec: OrchestratedAgentSpec,
) -> OrchestratorAgentProtocol:
    """Materialize one :class:`OrchestratedAgentSpec` as an orchestrator-shaped agent.

    Calls ``spec.agent_factory()`` to get a :class:`CalibratedAgent`,
    then wraps it via :func:`to_orchestrator_agent`. The returned
    object satisfies :class:`OrchestratorAgentProtocol` and carries:

    - ``spec.tags`` under :attr:`~lub.protocols.AuditKey.TAGS`
      (only when non-empty).
    - Each entry in ``spec.metadata`` merged into the agent's
      ``metadata`` dict (lub-managed keys like ``last_confidence`` take
      precedence over user metadata if there is a name collision).

    Args:
        spec: The declarative spec.

    Returns:
        An orchestrator-shaped agent ready to register.
    """
    agent = spec.agent_factory()
    shaped = to_orchestrator_agent(
        agent,
        name=spec.name,
        description=spec.description,
    )
    if spec.tags:
        shaped.metadata[AuditKey.TAGS] = list(spec.tags)
    for key, value in spec.metadata.items():
        # Lub-managed keys win on collision; user metadata fills the rest.
        shaped.metadata.setdefault(key, value)
    return shaped


def build_orchestrated_pack(
    specs: Iterable[OrchestratedAgentSpec],
) -> list[OrchestratorAgentProtocol]:
    """Materialize a list of orchestrated agent specs.

    Convenience wrapper around :func:`build_calibrated_orchestrated_member`
    that also rejects duplicate names eagerly (most orchestrators reject
    duplicates at registration anyway, but failing here gives a clearer
    error and avoids partial-registration states).

    Args:
        specs: Iterable of :class:`OrchestratedAgentSpec`.

    Returns:
        List of orchestrator-shaped agents in the same order as the
        input specs.

    Raises:
        ValueError: If two specs share the same ``name``.
    """
    seen: set[str] = set()
    pack: list[OrchestratorAgentProtocol] = []
    for spec in specs:
        if spec.name in seen:
            raise ValueError(
                f"duplicate orchestrated member name: {spec.name!r}; "
                f"orchestration frameworks reject duplicates"
            )
        seen.add(spec.name)
        pack.append(build_calibrated_orchestrated_member(spec))
    return pack


def dispatch_by_domain(
    specs: Iterable[OrchestratedAgentSpec],
    domain: str,
) -> list[OrchestratedAgentSpec]:
    """Filter ``specs`` to those whose ``domain`` matches, sorted for dispatch.

    Pattern 2 from :doc:`planning/30_Generic_Architecture_Spec`. Sort
    order is ``(-priority, name)`` -- higher priority first, lex tie-break
    on ``name`` so the result is deterministic for audit logs.

    Asking for a ``domain`` that is not in :data:`ALLOWED_DOMAINS`
    returns ``[]`` rather than raising; the validation contract is
    enforced at spec construction time, so a caller passing an unknown
    string here is asking for a (legitimately) empty filter result.

    Args:
        specs: Iterable of :class:`OrchestratedAgentSpec`.
        domain: Domain key to filter on.

    Returns:
        Specs whose ``domain == domain``, ordered for dispatch.
    """
    matched = [s for s in specs if s.domain == domain]
    matched.sort(key=lambda s: (-s.priority, s.name))
    return matched
