"""
lub.agents.adapters — framework adapters for CalibratedAgent.

Each adapter wraps a CalibratedAgent into the native node / agent / tool
shape of a specific orchestration framework. The four framework-specific
adapters are gated behind optional extras:

- ``pip install lub[langgraph]`` — for lub.agents.adapters.langgraph
- ``pip install lub[crewai]``    — for lub.agents.adapters.crewai
- ``pip install lub[autogen]``   — for lub.agents.adapters.autogen
- ``pip install lub[ruflo]``     — for lub.agents.adapters.ruflo

Importing an extras-gated adapter without the corresponding extra raises
ImportError with a clear install hint.

The canonical framework-agnostic bridge
:mod:`lub.agents.adapters.orchestrator` ships with the core install (no
extras required). It is the Protocol-based adapter
(:class:`lub.agents.protocols.OrchestratorAgentProtocol`) that the four
extras-gated adapters above all delegate to per pass 25 (post-ADR-002
generalization); :mod:`lub.agents.adapters.ruflo` in particular is now
a back-compat shim that re-exports from ``orchestrator``.
"""
