# Copyright 2026 Rafael Martins Alves - Apache-2.0
"""Tests for ``lub.runtime.ruflo_engine``.

Covers the ruflo-as-core entry point introduced by ADR-002:
``SwarmMemberSpec`` validation, ``build_calibrated_swarm_member``, and
``build_swarm_pack`` (including duplicate-name rejection and metadata
propagation).
"""

from __future__ import annotations

from typing import Any

import pytest

from lub.agents.adapters.ruflo import RufloAgentProtocol
from lub.agents.core import CalibratedAgent, RunReport
from lub.runtime import (
    SwarmMemberSpec,
    build_calibrated_swarm_member,
    build_swarm_pack,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


class _Echo(CalibratedAgent[Any, Any]):
    """Trivial CalibratedAgent for tests; supplies its own .run()."""

    prompt_template = "{x}"

    def __init__(self, response: str = "ok", confidence: float = 0.9) -> None:
        super().__init__(backend=object(), uncertainty=object(), policy=None)
        self._response = response
        self._confidence = confidence

    def parse(self, raw: str) -> str:
        return raw

    def run(self, input: Any) -> RunReport[Any, Any]:
        return RunReport(
            input=input,
            output=f"{self._response}::{input}",
            confidence=self._confidence,
        )


def _factory_for(response: str = "ok", confidence: float = 0.9):
    """Return a zero-argument factory producing an _Echo."""
    def _make() -> _Echo:
        return _Echo(response=response, confidence=confidence)
    return _make


# ---------------------------------------------------------------------------
# SwarmMemberSpec validation
# ---------------------------------------------------------------------------


def test_swarm_member_spec_basic():
    spec = SwarmMemberSpec(
        name="basel_reporter",
        description="Basel III Pillar 3 reporter",
        agent_factory=_factory_for(),
    )
    assert spec.name == "basel_reporter"
    assert spec.description == "Basel III Pillar 3 reporter"
    assert spec.tags == ()


def test_swarm_member_spec_with_tags():
    spec = SwarmMemberSpec(
        name="x",
        description=None,
        agent_factory=_factory_for(),
        tags=("regulatory", "basel-iii"),
    )
    assert spec.tags == ("regulatory", "basel-iii")


def test_swarm_member_spec_rejects_empty_name():
    with pytest.raises(ValueError, match="non-empty"):
        SwarmMemberSpec(
            name="",
            description=None,
            agent_factory=_factory_for(),
        )


def test_swarm_member_spec_rejects_non_callable_factory():
    with pytest.raises(TypeError, match="callable"):
        SwarmMemberSpec(
            name="x",
            description=None,
            agent_factory="not callable",  # type: ignore[arg-type]
        )


def test_swarm_member_spec_is_frozen():
    """Spec is a frozen dataclass; can't mutate after construction."""
    spec = SwarmMemberSpec(
        name="x",
        description=None,
        agent_factory=_factory_for(),
    )
    with pytest.raises((AttributeError, TypeError)):
        spec.name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# build_calibrated_swarm_member
# ---------------------------------------------------------------------------


def test_build_member_returns_ruflo_shaped():
    spec = SwarmMemberSpec(
        name="basel_reporter",
        description="basel",
        agent_factory=_factory_for(),
    )
    member = build_calibrated_swarm_member(spec)
    assert member.name == "basel_reporter"
    assert member.description == "basel"
    assert isinstance(member, RufloAgentProtocol)


def test_build_member_propagates_tags_to_metadata():
    spec = SwarmMemberSpec(
        name="x",
        description=None,
        agent_factory=_factory_for(),
        tags=("regulatory", "basel-iii"),
    )
    member = build_calibrated_swarm_member(spec)
    assert member.metadata["tags"] == ["regulatory", "basel-iii"]


def test_build_member_no_tags_omits_tags_metadata_key():
    """No tags supplied → no spurious 'tags' key in metadata."""
    spec = SwarmMemberSpec(
        name="x",
        description=None,
        agent_factory=_factory_for(),
    )
    member = build_calibrated_swarm_member(spec)
    assert "tags" not in member.metadata


def test_build_member_calibration_is_preserved_on_run():
    spec = SwarmMemberSpec(
        name="x",
        description=None,
        agent_factory=_factory_for(response="answer", confidence=0.85),
    )
    member = build_calibrated_swarm_member(spec)
    out = member.run("query")
    assert out == "answer::query"
    assert member.metadata["last_confidence"] == pytest.approx(0.85)


def test_build_member_factory_invoked_each_time_member_built():
    """Each build_calibrated_swarm_member call invokes the factory exactly once."""
    counter = {"n": 0}

    def factory() -> _Echo:
        counter["n"] += 1
        return _Echo()

    spec = SwarmMemberSpec(name="x", description=None, agent_factory=factory)
    build_calibrated_swarm_member(spec)
    build_calibrated_swarm_member(spec)
    assert counter["n"] == 2


# ---------------------------------------------------------------------------
# build_swarm_pack
# ---------------------------------------------------------------------------


def test_build_swarm_pack_basic():
    specs = [
        SwarmMemberSpec(name="a", description=None, agent_factory=_factory_for()),
        SwarmMemberSpec(name="b", description=None, agent_factory=_factory_for()),
        SwarmMemberSpec(name="c", description=None, agent_factory=_factory_for()),
    ]
    pack = build_swarm_pack(specs)
    assert len(pack) == 3
    assert [m.name for m in pack] == ["a", "b", "c"]


def test_build_swarm_pack_preserves_order():
    """Output order matches input order (stable)."""
    specs = [
        SwarmMemberSpec(name=f"agent_{i}", description=None, agent_factory=_factory_for())
        for i in range(5)
    ]
    pack = build_swarm_pack(specs)
    assert [m.name for m in pack] == [f"agent_{i}" for i in range(5)]


def test_build_swarm_pack_rejects_duplicate_names():
    spec = SwarmMemberSpec(name="dup", description=None, agent_factory=_factory_for())
    with pytest.raises(ValueError, match="duplicate.*member name"):
        build_swarm_pack([spec, spec])


def test_build_swarm_pack_rejects_duplicates_with_different_factories():
    """Duplicate detection is on the name, not on the factory identity."""
    s1 = SwarmMemberSpec(name="x", description="first", agent_factory=_factory_for("a"))
    s2 = SwarmMemberSpec(name="x", description="second", agent_factory=_factory_for("b"))
    with pytest.raises(ValueError, match="duplicate"):
        build_swarm_pack([s1, s2])


def test_build_swarm_pack_empty_input():
    """Empty iterable yields an empty pack (not an error)."""
    pack = build_swarm_pack([])
    assert pack == []


def test_build_swarm_pack_accepts_generator():
    """Spec source can be any iterable, including a generator."""
    def gen():
        yield SwarmMemberSpec(name="a", description=None, agent_factory=_factory_for())
        yield SwarmMemberSpec(name="b", description=None, agent_factory=_factory_for())

    pack = build_swarm_pack(gen())
    assert len(pack) == 2


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_exports_present():
    """The names listed in __all__ resolve when importing from lub.runtime."""
    import lub.runtime as runtime
    for name in ("SwarmMemberSpec", "build_calibrated_swarm_member", "build_swarm_pack"):
        assert hasattr(runtime, name), f"lub.runtime missing public symbol: {name}"
