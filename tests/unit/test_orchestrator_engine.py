# Copyright 2026 Rafael Martins Alves - Apache-2.0
"""Tests for ``lub.runtime.engine`` (canonical) + ruflo_engine alias parity.

Full behavioral coverage of the engine lives in
``test_runtime_ruflo_engine.py`` (those tests run against the same code
via the back-compat aliases). This file verifies the canonical generic
names exist, work, and that the swarm-flavored aliases point to the
same objects.
"""

from __future__ import annotations

from typing import Any

import pytest

from lub.agents.core import CalibratedAgent, RunReport
from lub.runtime import (
    SwarmMemberSpec,
    build_calibrated_swarm_member,
    build_swarm_pack,
    ruflo_engine,
)
from lub.runtime.engine import (
    OrchestratedAgentSpec,
    build_calibrated_orchestrated_member,
    build_orchestrated_pack,
)

# ---------------------------------------------------------------------------
# Alias parity
# ---------------------------------------------------------------------------


def test_swarm_member_spec_is_orchestrated_agent_spec():
    assert SwarmMemberSpec is OrchestratedAgentSpec


def test_build_swarm_pack_is_build_orchestrated_pack():
    assert build_swarm_pack is build_orchestrated_pack


def test_build_calibrated_swarm_member_is_canonical():
    assert build_calibrated_swarm_member is build_calibrated_orchestrated_member


def test_ruflo_engine_module_aliases():
    """Aliases via the legacy module path also point to canonical objects."""
    assert ruflo_engine.SwarmMemberSpec is OrchestratedAgentSpec
    assert ruflo_engine.build_swarm_pack is build_orchestrated_pack


# ---------------------------------------------------------------------------
# Canonical generic API works (smoke).
# ---------------------------------------------------------------------------


class _Echo(CalibratedAgent[Any, Any]):
    prompt_template = "{x}"
    def __init__(self, response: str = "ok") -> None:
        super().__init__(backend=object(), uncertainty=object(), policy=None)
        self._response = response
    def parse(self, raw: str) -> str:
        return raw
    def run(self, input: Any) -> RunReport[Any, Any]:
        return RunReport(input=input, output=self._response, confidence=0.9)


def test_orchestrated_agent_spec_basic():
    spec = OrchestratedAgentSpec(
        name="basel",
        description="d",
        agent_factory=lambda: _Echo(),
        tags=("regulatory",),
    )
    assert spec.name == "basel"
    assert spec.tags == ("regulatory",)


def test_build_calibrated_orchestrated_member_returns_protocol_satisfying_object():
    spec = OrchestratedAgentSpec(
        name="basel",
        description=None,
        agent_factory=lambda: _Echo(),
    )
    member = build_calibrated_orchestrated_member(spec)
    assert member.name == "basel"
    assert callable(member.run)


def test_build_orchestrated_pack_rejects_duplicates():
    spec = OrchestratedAgentSpec(
        name="dup", description=None, agent_factory=lambda: _Echo(),
    )
    with pytest.raises(ValueError, match="duplicate"):
        build_orchestrated_pack([spec, spec])


def test_build_orchestrated_pack_preserves_order():
    specs = [
        OrchestratedAgentSpec(
            name=f"a_{i}", description=None, agent_factory=lambda: _Echo(),
        )
        for i in range(3)
    ]
    pack = build_orchestrated_pack(specs)
    assert [m.name for m in pack] == ["a_0", "a_1", "a_2"]
