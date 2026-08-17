"""
lub.agents -- calibration layer for agent orchestration.

This subpackage is in **beta** as of lub v0.2. API may change between
minor releases until v0.3 stable. See `planning/RFC_001_calibrated_agents.md`
in the repo for the full design.

Minimal example:

    from lub.agents import CalibratedAgent, RefusalPolicy
    from lub.uncertainty import SemanticEntropy
    from lub.wrappers import HFBackend

    backend = HFBackend("Qwen/Qwen2.5-0.5B-Instruct")
    policy = RefusalPolicy(threshold=0.35)

    class MyAgent(CalibratedAgent):
        prompt_template = "Answer: {query}"

        def parse(self, raw: str) -> str:
            return raw.strip()

    agent = MyAgent(
        backend=backend,
        uncertainty=SemanticEntropy(backend),
        policy=policy,
    )
    report = agent.run({"query": "What is Basel III Tier 1?"})

Framework adapters live in `lub.agents.adapters.*` and are gated
behind optional extras (`pip install lub[langgraph]` etc.).

.. note::
   The dataclass :class:`lub.agents.policies.PolicyDecision` is planned
   to be renamed to ``AgentDecision`` at the v0.3 cut so it stops
   colliding with the same-named **enum** in :mod:`lub.policies` (used
   by the guard layer). The alias is documented in the
   :mod:`lub.agents.policies` module docstring rather than re-exported
   here because the project linter strips bare module-body aliases (per
   ``CHANGES_2026-04-26.md`` §2.4). New code should import
   :class:`PolicyDecision` from :mod:`lub.agents.policies` by name today
   and migrate at the v0.3 cut.
"""

from lub.agents.core import CalibratedAgent, RunReport
from lub.agents.policies import (
    AndPolicy,
    ConditionalPolicy,
    OrPolicy,
    PerFieldPolicy,
    RefusalPolicy,
)
from lub.agents.protocols import OrchestratorAgentProtocol
from lub.agents.reporter import AuditTrail, ReportingAgent

__all__ = [
    "AndPolicy",
    "AuditTrail",
    "CalibratedAgent",
    "ConditionalPolicy",
    "OrchestratorAgentProtocol",
    "OrPolicy",
    "PerFieldPolicy",
    "RefusalPolicy",
    "ReportingAgent",
    "RunReport",
]
