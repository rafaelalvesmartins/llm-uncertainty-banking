"""
lub.agents.adapters.autogen — translate a CalibratedAgent to a Microsoft
AutoGen AssistantAgent.

Install with: ``pip install lub[autogen]``.

Design target:

    from lub.agents.adapters.autogen import to_autogen_agent

    autogen_agent = to_autogen_agent(my_calibrated_agent, name="calibrated_qa")
"""

from __future__ import annotations

import importlib.util
from typing import Any

from lub.agents.core import CalibratedAgent

__all__ = ["to_autogen_agent"]

if importlib.util.find_spec("autogen_agentchat") is None:  # pragma: no cover
    raise ImportError(
        "lub.agents.adapters.autogen requires the `autogen` extra. "
        "Install with: pip install 'lub[autogen]'"
    )


def to_autogen_agent(
    agent: CalibratedAgent[Any, Any],
    *,
    name: str,
    system_message: str | None = None,
) -> Any:
    """Translate a CalibratedAgent into an AutoGen AssistantAgent.

    Args:
        agent: A CalibratedAgent instance.
        name: AutoGen agent name.
        system_message: Optional system message; if omitted, derived from
            the CalibratedAgent's prompt_template.

    Returns:
        An autogen_agentchat.AssistantAgent (or compatible).

    DEFER (v0.3) — full wiring lands in v0.3.
    """
    raise NotImplementedError(
        "to_autogen_agent is a scaffold. Full wiring lands in lub v0.3."
        " Install the agents-beta extra now to get the wired surface:"
        " pip install 'llm-uncertainty-banking[agents-beta]'."
    )
