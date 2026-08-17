"""
lub.agents.adapters.ruflo -- ruflo-flavored aliases for the generic
orchestrator adapter.

This module is a **back-compat shim** as of pass 25 (post ADR-002
generalization). The real implementation lives in
:mod:`lub.agents.adapters.orchestrator`. Names exported here:

- :class:`RufloAgentProtocol` -> alias of :class:`OrchestratorAgentProtocol`
- :func:`to_ruflo_agent` -> alias of :func:`to_orchestrator_agent`
- :func:`from_ruflo_agent` -> alias of :func:`from_orchestrator_agent`

Existing callers that import from ``lub.agents.adapters.ruflo`` continue
to work unchanged. New code should prefer the generic names from
:mod:`lub.agents.adapters.orchestrator`, which makes the framework-agnostic
design explicit.

Why we kept the ruflo-named entry points: ruflo (``ruvnet/ruflo``,
npm ``claude-flow``, MIT) is the canonical reference target for the
Protocol and is referenced throughout the petition / planning docs.
The aliases preserve those references; the underlying code is generic.

See also:

- :mod:`lub.agents.adapters.orchestrator` -- the canonical generic adapter.
- ``planning/ADRs/ADR-002_ruflo_as_orchestration_core_2026-04-25.md`` --
  the architectural decision recording the ruflo-as-core repositioning
  and (in pass 25) its generalization to any orchestrator.
- ``planning/27_Ruflo_Adapter_Expansion_Spec_2026-04-25.md`` -- the
  ruflo-flavored framing of the same bridge.
"""

from __future__ import annotations

from lub.agents.adapters.orchestrator import (
    OrchestratorAgentProtocol as RufloAgentProtocol,
)
from lub.agents.adapters.orchestrator import (
    from_orchestrator_agent as from_ruflo_agent,
)
from lub.agents.adapters.orchestrator import (
    to_orchestrator_agent as to_ruflo_agent,
)

__all__ = [
    "RufloAgentProtocol",
    "from_ruflo_agent",
    "to_ruflo_agent",
]
