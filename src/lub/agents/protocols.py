# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Structural protocols for cross-framework agent integration.

Pattern 1.2 from ``planning/26_Decoupling_Refactor_Plan_2026-04-25.md``.

Before pass 30 the canonical agent Protocol lived inside
``lub.agents.adapters.orchestrator`` and ``lub.agents.adapters.ruflo``
imported it sibling-to-sibling. Adapters depending on adapters is a
smell — if the orchestrator adapter is moved or refactored, every
sibling breaks.

Pass 30 lifts the Protocol out of the adapter folder. All adapters
(``orchestrator``, ``ruflo``, ``langgraph``, ``crewai``, ``autogen``,
and any future ones) import from this module. The original location
keeps a re-export shim for one minor version, so external code does
not break.

See ``src/lub/agents/README.md`` for the full agent-trinity (ABC vs
Protocol vs Spec) explainer.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class OrchestratorAgentProtocol(Protocol):
    """Minimum interface a framework-orchestrated agent must satisfy.

    Defined here in pure Python so we do not take a hard dependency
    on any specific orchestration framework (ruflo, langgraph, crewai,
    autogen, ...). Anything implementing ``.name`` and
    ``.run(input) -> Any`` is a valid input to
    :func:`lub.agents.adapters.orchestrator.from_orchestrator_agent`.

    Optional attributes (``description``, ``metadata``) are read when
    present and ignored otherwise.

    Reference targets — frameworks the Protocol is known to fit:

    * ``ruvnet/ruflo`` (npm: ``claude-flow``, MIT) — canonical reference.
    * ``langgraph`` — node objects with ``run``.
    * ``crewai`` — ``Agent`` instances with ``execute``-shaped runners.
    * ``autogen`` — ``AssistantAgent`` instances.
    """

    name: str

    def run(self, input: Any) -> Any:
        """Execute the orchestrator agent on the given input and
        return its output."""
        ...


__all__ = ["OrchestratorAgentProtocol"]
