"""
lub.agents.adapters.langgraph — translate a CalibratedAgent to a
LangGraph-compatible node.

Install with: ``pip install lub[langgraph]``.

All concrete behavior is DEFER (v0.3). The design target is:

    from lub.agents import CalibratedAgent
    from lub.agents.adapters.langgraph import to_langgraph_node

    agent = MyCalibratedAgent(...)
    node = to_langgraph_node(agent)
    graph.add_node("my_agent", node)

The returned node:

1. Accepts the graph's state dict.
2. Invokes the CalibratedAgent on the relevant state slice.
3. Returns a state update dict that includes both the agent's
   structured output AND a ``lub_run_report`` key for audit trail.

.. note::
   ``# TODO`` markers in this module have been retired in favor of
   ``DEFER (v0.3)`` to match the convention established across
   :mod:`lub.agents` (see :mod:`lub.agents.core`,
   :mod:`lub.agents.policies`, :mod:`lub.agents.reporter`, and the
   sibling ``autogen`` / ``crewai`` adapters which already used the
   non-``TODO`` form). The :class:`NotImplementedError` raises below
   are the v0.3 wiring points.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from typing import Any

from lub.agents.core import CalibratedAgent

__all__ = ["to_langgraph_node", "LangGraphCompiler"]

if importlib.util.find_spec("langgraph") is None:  # pragma: no cover
    raise ImportError(
        "lub.agents.adapters.langgraph requires the `langgraph` extra. "
        "Install with: pip install 'lub[langgraph]'"
    )


def to_langgraph_node(
    agent: CalibratedAgent[Any, Any],
    *,
    input_key: str = "input",
    output_key: str = "output",
    report_key: str = "lub_run_report",
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Translate a CalibratedAgent into a LangGraph node callable.

    Args:
        agent: A CalibratedAgent instance.
        input_key: Key in the graph state dict that carries the agent input.
        output_key: Key in the returned state update where the agent's
            structured output is placed.
        report_key: Key where the full RunReport (serialized) is placed for
            downstream audit-trail capture.

    Returns:
        A callable compatible with ``graph.add_node(name, callable)``.

    DEFER (v0.3) — full wiring lands in v0.3 per RFC-001.
    """
    raise NotImplementedError(
        "to_langgraph_node is a scaffold. Full wiring lands in lub v0.3. "
        "See planning/RFC_001_calibrated_agents_2026-04-23.md."
        " Install the agents-beta extra now to get the wired surface:"
        " pip install 'llm-uncertainty-banking[agents-beta]'."
    )


class LangGraphCompiler:
    """Helper for compiling a set of CalibratedAgents into a graph.

    Intended for users who want to compose multiple calibrated agents into
    a single LangGraph graph with shared policy and uncertainty config.

    DEFER (v0.3) — not yet implemented.
    """

    def __init__(self, *agents: CalibratedAgent[Any, Any]) -> None:
        self.agents = agents

    def build(self) -> Any:
        """Compile the registered agents into a LangGraph graph. DEFER (v0.3)."""
        raise NotImplementedError(
            "LangGraphCompiler.build is a scaffold. Lands in v0.3."
            " Install the agents-beta extra now to get the wired surface:"
            " pip install 'llm-uncertainty-banking[agents-beta]'."
        )
