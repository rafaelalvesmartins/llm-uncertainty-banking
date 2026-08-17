# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Hermetic tests for the domain-grouping fields on OrchestratedAgentSpec
(Pattern 2)."""

from __future__ import annotations

import pytest

from lub.runtime.engine import (
    ALLOWED_DOMAINS,
    OrchestratedAgentSpec,
    dispatch_by_domain,
)

# ---------------------------------------------------------------------------
# ALLOWED_DOMAINS taxonomy
# ---------------------------------------------------------------------------


def test_allowed_domains_are_banking_partition():
    assert "risk" in ALLOWED_DOMAINS
    assert "compliance" in ALLOWED_DOMAINS
    assert "audit" in ALLOWED_DOMAINS
    assert "model_validation" in ALLOWED_DOMAINS


def test_allowed_domains_is_frozenset():
    # Immutable so callers can't accidentally extend it at runtime.
    assert isinstance(ALLOWED_DOMAINS, frozenset)


# ---------------------------------------------------------------------------
# OrchestratedAgentSpec construction
# ---------------------------------------------------------------------------


def _spec(name: str = "agent_a", **kwargs):
    """Helper: build a minimal spec.

    The agent factory is a no-op lambda. Domain-grouping tests don't
    care about factory shape — only about the metadata.
    """
    defaults = dict(
        name=name,
        description="test agent",
        agent_factory=lambda: object(),
    )
    defaults.update(kwargs)
    return OrchestratedAgentSpec(**defaults)


def test_default_domain_is_compliance():
    s = _spec()
    assert s.domain == "compliance"


def test_default_priority_is_zero():
    s = _spec()
    assert s.priority == 0


def test_default_parallel_safe_is_false():
    s = _spec()
    assert s.parallel_safe is False


def test_explicit_domain_priority_parallel():
    s = _spec(domain="risk", priority=10, parallel_safe=True)
    assert s.domain == "risk"
    assert s.priority == 10
    assert s.parallel_safe is True


def test_unknown_domain_raises():
    with pytest.raises(ValueError):
        _spec(domain="hr")


def test_empty_domain_raises():
    with pytest.raises(ValueError):
        _spec(domain="")


# ---------------------------------------------------------------------------
# dispatch_by_domain
# ---------------------------------------------------------------------------


def test_dispatch_by_domain_filters_correctly():
    a = _spec(name="a", domain="risk", priority=1)
    b = _spec(name="b", domain="compliance", priority=1)
    c = _spec(name="c", domain="risk", priority=2)
    out = dispatch_by_domain([a, b, c], domain="risk")
    assert {s.name for s in out} == {"a", "c"}


def test_dispatch_by_domain_sorts_by_priority_desc():
    a = _spec(name="a", domain="risk", priority=1)
    c = _spec(name="c", domain="risk", priority=5)
    b = _spec(name="b", domain="risk", priority=3)
    out = dispatch_by_domain([a, c, b], domain="risk")
    assert [s.name for s in out] == ["c", "b", "a"]


def test_dispatch_by_domain_breaks_priority_tie_by_name():
    a = _spec(name="zeta", domain="risk", priority=1)
    b = _spec(name="alpha", domain="risk", priority=1)
    out = dispatch_by_domain([a, b], domain="risk")
    # Stable: alpha < zeta lexicographically.
    assert [s.name for s in out] == ["alpha", "zeta"]


def test_dispatch_by_domain_returns_empty_when_no_match():
    a = _spec(name="a", domain="risk")
    assert dispatch_by_domain([a], domain="audit") == []


def test_dispatch_by_domain_unknown_domain_returns_empty():
    # Asking for an unknown domain returns [] rather than raising —
    # the validation happens at spec construction.
    a = _spec(name="a", domain="risk")
    assert dispatch_by_domain([a], domain="hr") == []
