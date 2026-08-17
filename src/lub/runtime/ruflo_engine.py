"""
lub.runtime.ruflo_engine -- ruflo-flavored aliases for the generic engine.

Back-compat shim as of pass 25 (post ADR-002 generalization). The real
implementation lives in :mod:`lub.runtime.engine`. Names exported here:

- :class:`SwarmMemberSpec` -> alias of :class:`OrchestratedAgentSpec`
- :func:`build_calibrated_swarm_member` -> alias of
  :func:`build_calibrated_orchestrated_member`
- :func:`build_swarm_pack` -> alias of :func:`build_orchestrated_pack`

New code should prefer the generic names from :mod:`lub.runtime.engine`.
"""

from __future__ import annotations

from lub.runtime.engine import (
    OrchestratedAgentSpec as SwarmMemberSpec,
)
from lub.runtime.engine import (
    build_calibrated_orchestrated_member as build_calibrated_swarm_member,
)
from lub.runtime.engine import (
    build_orchestrated_pack as build_swarm_pack,
)

__all__ = [
    "SwarmMemberSpec",
    "build_calibrated_swarm_member",
    "build_swarm_pack",
]
