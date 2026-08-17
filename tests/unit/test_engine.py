"""Tests for lub.runtime.engine -- orchestration factory helpers."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pytest

from lub.protocols import AuditKey
from lub.runtime.engine import (
    ALLOWED_DOMAINS,
    OrchestratedAgentSpec,
    build_calibrated_orchestrated_member,
    build_orchestrated_pack,
    dispatch_by_domain,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dummy_factory():
    """A zero-arg callable returning a fresh MagicMock 'agent' on each call."""
    return lambda: MagicMock(name="calibrated_agent")


@pytest.fixture
def fake_shaped_agent():
    """A fake orchestrator-shaped agent with a mutable metadata dict."""
    shaped = MagicMock(name="shaped_agent")
    shaped.metadata = {}
    return shaped


@pytest.fixture
def patched_to_orchestrator(fake_shaped_agent):
    """Patch ``to_orchestrator_agent`` so tests don't need the real adapter."""
    with patch(
        "lub.runtime.engine.to_orchestrator_agent",
        return_value=fake_shaped_agent,
    ) as p:
        yield p


# ---------------------------------------------------------------------------
# ALLOWED_DOMAINS
# ---------------------------------------------------------------------------


class TestAllowedDomains:
    def test_contents(self):
        assert ALLOWED_DOMAINS == frozenset(
            {"risk", "compliance", "audit", "model_validation"}
        )

    def test_is_frozen(self):
        assert isinstance(ALLOWED_DOMAINS, frozenset)
        with pytest.raises(AttributeError):
            ALLOWED_DOMAINS.add("new_domain")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# OrchestratedAgentSpec
# ---------------------------------------------------------------------------


class TestOrchestratedAgentSpec:
    def test_minimal_construction_defaults(self, dummy_factory):
        spec = OrchestratedAgentSpec(name="x", agent_factory=dummy_factory)
        assert spec.name == "x"
        assert spec.description is None
        assert spec.tags == ()
        assert dict(spec.metadata) == {}
        assert spec.domain == "compliance"
        assert spec.priority == 0
        assert spec.parallel_safe is False

    def test_full_construction(self, dummy_factory):
        spec = OrchestratedAgentSpec(
            name="basel_reporter",
            agent_factory=dummy_factory,
            description="Basel III reporter",
            tags=("regulatory", "basel-iii"),
            metadata={"owner": "mrm-team", "sla_p95_ms": 800},
            domain="risk",
            priority=5,
            parallel_safe=True,
        )
        assert spec.description == "Basel III reporter"
        assert spec.tags == ("regulatory", "basel-iii")
        assert spec.metadata["owner"] == "mrm-team"
        assert spec.domain == "risk"
        assert spec.priority == 5
        assert spec.parallel_safe is True

    def test_empty_name_raises(self, dummy_factory):
        with pytest.raises(ValueError, match="non-empty"):
            OrchestratedAgentSpec(name="", agent_factory=dummy_factory)

    def test_non_callable_agent_factory_raises_typeerror(self):
        with pytest.raises(TypeError, match="callable"):
            OrchestratedAgentSpec(
                name="x",
                agent_factory="not-callable",  # type: ignore[arg-type]
            )

    def test_invalid_domain_raises(self, dummy_factory):
        with pytest.raises(ValueError, match="domain"):
            OrchestratedAgentSpec(
                name="x", agent_factory=dummy_factory, domain="not-a-domain"
            )

    @pytest.mark.parametrize("domain", sorted(ALLOWED_DOMAINS))
    def test_each_allowed_domain_accepted(self, dummy_factory, domain):
        spec = OrchestratedAgentSpec(
            name="x", agent_factory=dummy_factory, domain=domain
        )
        assert spec.domain == domain

    def test_spec_is_frozen(self, dummy_factory):
        spec = OrchestratedAgentSpec(name="x", agent_factory=dummy_factory)
        with pytest.raises(FrozenInstanceError):
            spec.name = "y"  # type: ignore[misc]

    def test_default_metadata_is_immutable(self, dummy_factory):
        spec = OrchestratedAgentSpec(name="x", agent_factory=dummy_factory)
        with pytest.raises(TypeError):
            spec.metadata["k"] = "v"  # type: ignore[index]

    def test_default_metadata_not_shared_state_across_instances(
        self, dummy_factory
    ):
        s1 = OrchestratedAgentSpec(name="a", agent_factory=dummy_factory)
        s2 = OrchestratedAgentSpec(name="b", agent_factory=dummy_factory)
        # The two specs may share the same read-only sentinel, but mutating
        # it must be impossible regardless.
        with pytest.raises(TypeError):
            s1.metadata["leak"] = "yes"  # type: ignore[index]
        assert dict(s2.metadata) == {}


# ---------------------------------------------------------------------------
# build_calibrated_orchestrated_member
# ---------------------------------------------------------------------------


class TestBuildCalibratedOrchestratedMember:
    def test_invokes_factory_and_adapter(
        self, patched_to_orchestrator, fake_shaped_agent
    ):
        inner = MagicMock(name="inner_agent")
        factory = MagicMock(return_value=inner)
        spec = OrchestratedAgentSpec(
            name="alpha", agent_factory=factory, description="desc"
        )
        result = build_calibrated_orchestrated_member(spec)
        factory.assert_called_once_with()
        patched_to_orchestrator.assert_called_once_with(
            inner, name="alpha", description="desc"
        )
        assert result is fake_shaped_agent

    def test_tags_recorded_when_non_empty(
        self, patched_to_orchestrator, fake_shaped_agent, dummy_factory
    ):
        spec = OrchestratedAgentSpec(
            name="alpha",
            agent_factory=dummy_factory,
            tags=("regulatory", "basel-iii"),
        )
        build_calibrated_orchestrated_member(spec)
        assert fake_shaped_agent.metadata[AuditKey.TAGS] == [
            "regulatory",
            "basel-iii",
        ]

    def test_tags_not_recorded_when_empty(
        self, patched_to_orchestrator, fake_shaped_agent, dummy_factory
    ):
        spec = OrchestratedAgentSpec(name="alpha", agent_factory=dummy_factory)
        build_calibrated_orchestrated_member(spec)
        assert AuditKey.TAGS not in fake_shaped_agent.metadata

    def test_user_metadata_merged(
        self, patched_to_orchestrator, fake_shaped_agent, dummy_factory
    ):
        spec = OrchestratedAgentSpec(
            name="alpha",
            agent_factory=dummy_factory,
            metadata={"owner": "mrm-team", "sla_p95_ms": 800},
        )
        build_calibrated_orchestrated_member(spec)
        assert fake_shaped_agent.metadata["owner"] == "mrm-team"
        assert fake_shaped_agent.metadata["sla_p95_ms"] == 800

    def test_lub_managed_keys_win_on_collision(
        self, patched_to_orchestrator, fake_shaped_agent, dummy_factory
    ):
        # Simulate a lub-managed key already present on the shaped agent.
        fake_shaped_agent.metadata["last_confidence"] = 0.92
        spec = OrchestratedAgentSpec(
            name="alpha",
            agent_factory=dummy_factory,
            metadata={"last_confidence": 0.0, "owner": "user"},
        )
        build_calibrated_orchestrated_member(spec)
        # setdefault means existing lub-managed value is preserved.
        assert fake_shaped_agent.metadata["last_confidence"] == 0.92
        # Non-colliding user metadata still flows through.
        assert fake_shaped_agent.metadata["owner"] == "user"

    def test_returns_object_satisfying_protocol_contract(
        self, patched_to_orchestrator, fake_shaped_agent, dummy_factory
    ):
        spec = OrchestratedAgentSpec(name="alpha", agent_factory=dummy_factory)
        result = build_calibrated_orchestrated_member(spec)
        # The shaped agent must expose a metadata mapping.
        assert hasattr(result, "metadata")
        assert isinstance(result.metadata, dict)


# ---------------------------------------------------------------------------
# build_orchestrated_pack
# ---------------------------------------------------------------------------


class TestBuildOrchestratedPack:
    def test_empty_input_returns_empty_list(self):
        assert build_orchestrated_pack([]) == []

    def test_materializes_each_spec_in_order(
        self, patched_to_orchestrator, dummy_factory
    ):
        shaped_agents = [
            MagicMock(name=f"shaped_{i}", metadata={}) for i in range(3)
        ]
        patched_to_orchestrator.side_effect = shaped_agents
        specs = [
            OrchestratedAgentSpec(name=f"agent_{i}", agent_factory=dummy_factory)
            for i in range(3)
        ]
        result = build_orchestrated_pack(specs)
        assert result == shaped_agents
        assert patched_to_orchestrator.call_count == 3

    def test_duplicate_names_raise_valueerror(
        self, patched_to_orchestrator, dummy_factory
    ):
        patched_to_orchestrator.side_effect = lambda *a, **kw: MagicMock(
            metadata={}
        )
        specs = [
            OrchestratedAgentSpec(name="dup", agent_factory=dummy_factory),
            OrchestratedAgentSpec(name="dup", agent_factory=dummy_factory),
        ]
        with pytest.raises(ValueError, match="duplicate"):
            build_orchestrated_pack(specs)

    def test_duplicate_detected_even_when_separated(
        self, patched_to_orchestrator, dummy_factory
    ):
        patched_to_orchestrator.side_effect = lambda *a, **kw: MagicMock(
            metadata={}
        )
        specs = [
            OrchestratedAgentSpec(name="a", agent_factory=dummy_factory),
            OrchestratedAgentSpec(name="b", agent_factory=dummy_factory),
            OrchestratedAgentSpec(name="a", agent_factory=dummy_factory),
        ]
        with pytest.raises(ValueError, match="duplicate"):
            build_orchestrated_pack(specs)

    def test_accepts_generator_input(
        self, patched_to_orchestrator, dummy_factory
    ):
        patched_to_orchestrator.side_effect = lambda *a, **kw: MagicMock(
            metadata={}
        )
        specs_gen = (
            OrchestratedAgentSpec(name=f"g_{i}", agent_factory=dummy_factory)
            for i in range(2)
        )
        result = build_orchestrated_pack(specs_gen)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# dispatch_by_domain
# ---------------------------------------------------------------------------


class TestDispatchByDomain:
    def test_filters_by_domain(self, dummy_factory):
        specs = [
            OrchestratedAgentSpec(
                name="a", agent_factory=dummy_factory, domain="risk"
            ),
            OrchestratedAgentSpec(
                name="b", agent_factory=dummy_factory, domain="audit"
            ),
            OrchestratedAgentSpec(
                name="c", agent_factory=dummy_factory, domain="risk"
            ),
        ]
        result = dispatch_by_domain(specs, "risk")
        names = [s.name for s in result]
        assert set(names) == {"a", "c"}
        assert "b" not in names

    def test_sort_priority_desc_then_name_asc(self, dummy_factory):
        specs = [
            OrchestratedAgentSpec(
                name="b", agent_factory=dummy_factory, domain="risk", priority=1
            ),
            OrchestratedAgentSpec(
                name="a", agent_factory=dummy_factory, domain="risk", priority=1
            ),
            OrchestratedAgentSpec(
                name="c", agent_factory=dummy_factory, domain="risk", priority=5
            ),
        ]
        result = dispatch_by_domain(specs, "risk")
        # priority=5 first, then priority=1 ties broken by name lexicographically.
        assert [s.name for s in result] == ["c", "a", "b"]

    def test_negative_priority_handled(self, dummy_factory):
        specs = [
            OrchestratedAgentSpec(
                name="low",
                agent_factory=dummy_factory,
                domain="risk",
                priority=-10,
            ),
            OrchestratedAgentSpec(
                name="hi",
                agent_factory=dummy_factory,
                domain="risk",
                priority=10,
            ),
            OrchestratedAgentSpec(
                name="zero",
                agent_factory=dummy_factory,
                domain="risk",
                priority=0,
            ),
        ]
        result = dispatch_by_domain(specs, "risk")
        assert [s.name for s in result] == ["hi", "zero", "low"]

    def test_unknown_domain_returns_empty(self, dummy_factory):
        specs = [
            OrchestratedAgentSpec(
                name="a", agent_factory=dummy_factory, domain="risk"
            ),
        ]
        assert dispatch_by_domain(specs, "not-a-real-domain") == []

    def test_empty_input_returns_empty(self):
        assert dispatch_by_domain([], "risk") == []

    def test_no_matching_specs_returns_empty(self, dummy_factory):
        specs = [
            OrchestratedAgentSpec(
                name="a", agent_factory=dummy_factory, domain="risk"
            ),
        ]
        assert dispatch_by_domain(specs, "audit") == []

    def test_deterministic_order_for_audit(self, dummy_factory):
        # Two runs with the same input must give exactly the same order.
        specs = [
            OrchestratedAgentSpec(
                name=n,
                agent_factory=dummy_factory,
                domain="compliance",
                priority=p,
            )
            for n, p in [("z", 1), ("a", 1), ("m", 2), ("b", 2)]
        ]
        run1 = dispatch_by_domain(specs, "compliance")
        run2 = dispatch_by_domain(specs, "compliance")
        assert [s.name for s in run1] == [s.name for s in run2]
        assert [s.name for s in run1] == ["b", "m", "a", "z"]
