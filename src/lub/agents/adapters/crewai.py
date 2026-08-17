"""
lub.agents.adapters.crewai — translate a CalibratedAgent to a CrewAI
Agent.

Install with: ``pip install lub[crewai]``.

Design target:

    from lub.agents.adapters.crewai import to_crewai_agent

    crewai_agent = to_crewai_agent(my_calibrated_agent, role="...", goal="...")

The returned CrewAI agent:

1. Uses the CalibratedAgent's backend + uncertainty + policy.
2. Wraps the CalibratedAgent.run() as the execute-task path.
3. Emits the RunReport into CrewAI's task output metadata so downstream
   steps can inspect confidence and refusal decisions.
"""

from __future__ import annotations

import importlib.util
from typing import Any

from lub.agents.core import CalibratedAgent

try:
    _crewai_available = importlib.util.find_spec("crewai") is not None
except (ValueError, ModuleNotFoundError):
    _crewai_available = False

if not _crewai_available:  # pragma: no cover
    raise ImportError(
        "lub.agents.adapters.crewai requires the `crewai` extra. "
        "Install with: pip install 'lub[crewai]'"
    )


def to_crewai_agent(
    agent: CalibratedAgent[Any, Any],
    *,
    role: str,
    goal: str,
    backstory: str | None = None,
) -> Any:
    """Translate a CalibratedAgent into a CrewAI Agent.

    Args:
        agent: A CalibratedAgent instance.
        role: CrewAI role string.
        goal: CrewAI goal string.
        backstory: Optional CrewAI backstory.

    Returns:
        A crewai.Agent (or compatible) instance.

    DEFER (v0.3) — full wiring lands in v0.3.
    """
    raise NotImplementedError(
        "to_crewai_agent is a scaffold. Full wiring lands in lub v0.3."
        " Install the agents-beta extra now to get the wired surface:"
        " pip install 'llm-uncertainty-banking[agents-beta]'."
    )
