# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""The public Decision enum must be reachable from a guard verdict.

``Decision.ESCALATE`` has always existed on the API surface, but until
``PolicyDecision.ESCALATE`` shipped the only way to produce it was an
HTTP 5xx. A guard that genuinely escalated was reported to the caller
as PASSTHROUGH — the opposite of what happened.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lub.connectors.bridge.api.models import Decision
from lub.connectors.bridge.api.routes import _audit_decision_for, _decision_for
from lub.guard import GuardResult, PolicyDecision, PolicyOutcome, rmf_subcategory
from lub.types import UncertaintyResult


def _bridge_result(decision: PolicyDecision) -> SimpleNamespace:
    raw = UncertaintyResult(answer="answer", confidence=0.81)
    outcome = PolicyOutcome(
        decision=decision,
        confidence=0.81,
        threshold=0.70,
        passed=True,
        answer="answer",
    )
    verdict = GuardResult(
        raw=raw,
        outcome=outcome,
        output="answer",
        rmf_subcategory=rmf_subcategory(decision),
    )
    return SimpleNamespace(escalated=False, primary=SimpleNamespace(guard_result=verdict))


def test_escalate_policy_maps_to_the_escalate_decision() -> None:
    assert _decision_for(_bridge_result(PolicyDecision.ESCALATE)) is Decision.ESCALATE


def test_escalate_reaches_the_audit_trail_by_name() -> None:
    assert _audit_decision_for(_bridge_result(PolicyDecision.ESCALATE)) == "escalate"


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (PolicyDecision.PASSTHROUGH, Decision.PASSTHROUGH),
        (PolicyDecision.FLAG, Decision.FLAG),
        (PolicyDecision.ABSTAIN, Decision.ABSTAIN),
    ],
)
def test_existing_mappings_are_unchanged(policy: PolicyDecision, expected: Decision) -> None:
    assert _decision_for(_bridge_result(policy)) is expected
