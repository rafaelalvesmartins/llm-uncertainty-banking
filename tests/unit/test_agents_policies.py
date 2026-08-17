"""
Tests for lub.agents.policies — RefusalPolicy and combinators.

RefusalPolicy.decide() is the only policy method with real behavior in
the scaffold; everything else raises NotImplementedError.
"""

from __future__ import annotations

import pytest


def test_refusal_policy_default_emits_at_high_confidence():
    from lub.agents import RefusalPolicy

    policy = RefusalPolicy(threshold=0.5)
    decision = policy.decide(confidence=0.9)
    assert decision.emit is True
    assert decision.action is None


def test_refusal_policy_refuses_at_low_confidence():
    from lub.agents import RefusalPolicy

    policy = RefusalPolicy(
        threshold=0.5, below_threshold_action="REQUIRES_HUMAN_REVIEW"
    )
    decision = policy.decide(confidence=0.2)
    assert decision.emit is False
    assert decision.action == "REQUIRES_HUMAN_REVIEW"


def test_refusal_policy_emits_at_exactly_threshold():
    from lub.agents import RefusalPolicy

    policy = RefusalPolicy(threshold=0.5)
    decision = policy.decide(confidence=0.5)
    assert decision.emit is True


def test_refusal_policy_validates_threshold_range():
    from lub.agents import RefusalPolicy

    with pytest.raises(ValueError, match="\\[0, 1\\]"):
        RefusalPolicy(threshold=1.5)
    with pytest.raises(ValueError, match="\\[0, 1\\]"):
        RefusalPolicy(threshold=-0.1)


def test_refusal_policy_rationale_is_populated():
    from lub.agents import RefusalPolicy

    policy = RefusalPolicy(threshold=0.5)
    emit_decision = policy.decide(confidence=0.8)
    refuse_decision = policy.decide(confidence=0.3)
    assert emit_decision.rationale is not None
    assert "0.800" in emit_decision.rationale
    assert refuse_decision.rationale is not None
    assert "0.300" in refuse_decision.rationale


def test_refusal_policy_apply_is_scaffold():
    from lub.agents import RefusalPolicy

    policy = RefusalPolicy(threshold=0.5)
    with pytest.raises(NotImplementedError, match="structured-output gating"):
        policy.apply(raw={"x": "y"}, confidence=0.9)


def test_per_field_policy_decide_requires_field():
    from lub.agents import PerFieldPolicy, RefusalPolicy

    per_field = PerFieldPolicy(
        field_policies={"x": RefusalPolicy(threshold=0.7)},
        default=RefusalPolicy(threshold=0.5),
    )
    with pytest.raises(NotImplementedError, match="field-level confidence"):
        per_field.decide(confidence=0.9)


def test_per_field_policy_decide_field_is_scaffold():
    from lub.agents import PerFieldPolicy, RefusalPolicy

    per_field = PerFieldPolicy(
        field_policies={"x": RefusalPolicy(threshold=0.7)},
        default=RefusalPolicy(threshold=0.5),
    )
    with pytest.raises(NotImplementedError):
        per_field.decide_field("x", confidence=0.9)


def test_and_policy_is_scaffold():
    from lub.agents import AndPolicy, RefusalPolicy

    combined = AndPolicy(policies=(RefusalPolicy(threshold=0.5),))
    with pytest.raises(NotImplementedError):
        combined.decide(confidence=0.9)


def test_or_policy_is_scaffold():
    from lub.agents import OrPolicy, RefusalPolicy

    combined = OrPolicy(policies=(RefusalPolicy(threshold=0.5),))
    with pytest.raises(NotImplementedError):
        combined.decide(confidence=0.9)


def test_conditional_policy_is_scaffold():
    from lub.agents import ConditionalPolicy, RefusalPolicy

    cond = ConditionalPolicy(
        predicate=lambda _: True,
        if_true=RefusalPolicy(threshold=0.7),
        if_false=RefusalPolicy(threshold=0.4),
    )
    with pytest.raises(NotImplementedError):
        cond.decide(confidence=0.9)
