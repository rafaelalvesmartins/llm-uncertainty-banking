# Copyright 2026 Rafael Martins Alves - Apache-2.0
"""Tests for ``lub.agents.adapters.orchestrator`` (canonical) + ruflo alias parity.

The full behavioral coverage lives in ``test_ruflo_adapter.py`` (those
tests run against the same code via the back-compat aliases). This
file verifies the canonical generic names work and that the ruflo
aliases point to the same objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from lub.agents.adapters import ruflo as ruflo_module
from lub.agents.adapters.orchestrator import (
    OrchestratorAgentProtocol,
    from_orchestrator_agent,
    to_orchestrator_agent,
)
from lub.agents.core import CalibratedAgent, RunReport
from lub.agents.policies import RefusalPolicy

# ---------------------------------------------------------------------------
# Alias parity: ruflo names point to the canonical orchestrator names.
# ---------------------------------------------------------------------------


def test_ruflo_protocol_is_orchestrator_protocol():
    assert ruflo_module.RufloAgentProtocol is OrchestratorAgentProtocol


def test_ruflo_to_is_orchestrator_to():
    assert ruflo_module.to_ruflo_agent is to_orchestrator_agent


def test_ruflo_from_is_orchestrator_from():
    assert ruflo_module.from_ruflo_agent is from_orchestrator_agent


# ---------------------------------------------------------------------------
# Canonical generic API works as expected (smoke).
# ---------------------------------------------------------------------------


@dataclass
class _GenericAgent:
    name: str
    description: str | None = None

    def run(self, input: Any) -> str:
        return f"out::{input}"


@dataclass
class _ConstUQ:
    confidence: float

    def score(self, prompt: str, output: Any) -> float:
        return self.confidence


def test_from_orchestrator_agent_returns_calibrated_agent():
    agent = _GenericAgent(name="generic")
    wrapped = from_orchestrator_agent(agent, uncertainty=_ConstUQ(0.9))
    assert isinstance(wrapped, CalibratedAgent)


def test_from_orchestrator_agent_runs_underlying_agent():
    agent = _GenericAgent(name="x")
    wrapped = from_orchestrator_agent(agent, uncertainty=_ConstUQ(0.5))
    report = wrapped.run("query")
    assert report.output == "out::query"


def test_audit_trail_uses_generic_adapter_label():
    agent = _GenericAgent(name="basel_reporter")
    wrapped = from_orchestrator_agent(agent, uncertainty=_ConstUQ(0.9))
    report = wrapped.run("q")
    assert report.audit_trail["adapter"] == "orchestrator"
    assert report.audit_trail["orchestrator_agent"] == "basel_reporter"


def test_to_orchestrator_agent_satisfies_protocol():
    class Echo(CalibratedAgent):
        prompt_template = "x"
        def parse(self, raw: str) -> str:
            return raw
        def run(self, input: Any) -> RunReport[Any, Any]:
            return RunReport(input=input, output="echo", confidence=0.9)

    shaped = to_orchestrator_agent(
        Echo(backend=object(), uncertainty=object(), policy=None),
        name="echo",
    )
    assert isinstance(shaped, OrchestratorAgentProtocol)
    assert shaped.run("anything") == "echo"


def test_refusal_policy_still_gates_with_canonical_api():
    agent = _GenericAgent(name="x")
    policy = RefusalPolicy(threshold=0.7)
    wrapped = from_orchestrator_agent(
        agent, uncertainty=_ConstUQ(0.5), policy=policy,
    )
    report = wrapped.run("q")
    assert report.output == "REQUIRES_HUMAN_REVIEW"
    assert report.refusal_flags["refused"] == "REQUIRES_HUMAN_REVIEW"


def test_rejects_object_without_run():
    class NotAnAgent:
        name = "x"

    with pytest.raises(TypeError, match=r"\.run\(\)"):
        from_orchestrator_agent(NotAnAgent(), uncertainty=_ConstUQ(0.5))
