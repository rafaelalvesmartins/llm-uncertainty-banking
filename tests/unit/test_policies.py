# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import json

import pytest

from lub.policies import PolicyDecision, PolicyOutcome, rmf_subcategory


def test_decision_values_are_stable_strings() -> None:
    assert PolicyDecision.ABSTAIN.value == "abstain"
    assert PolicyDecision.FLAG.value == "flag"
    assert PolicyDecision.PASSTHROUGH.value == "passthrough"
    assert PolicyDecision.RAISE.value == "raise"


def test_rmf_mapping_covers_every_decision() -> None:
    for decision in PolicyDecision:
        sub = rmf_subcategory(decision)
        assert sub
        assert " " in sub  # "MANAGE 2.3", "GOVERN 3.2", etc.


def test_outcome_to_dict_round_trips_via_json() -> None:
    outcome = PolicyOutcome(
        decision=PolicyDecision.ABSTAIN,
        confidence=0.42,
        threshold=0.5,
        passed=False,
        answer="42",
        reason="low confidence",
        metadata={"agreement": 0.4},
    )
    payload = outcome.to_dict()
    blob = json.dumps(payload, sort_keys=True)
    parsed = json.loads(blob)
    assert parsed["decision"] == "abstain"
    assert parsed["confidence"] == pytest.approx(0.42)
    assert parsed["metadata"] == {"agreement": 0.4}


def test_outcome_is_frozen() -> None:
    outcome = PolicyOutcome(
        decision=PolicyDecision.PASSTHROUGH,
        confidence=1.0,
        threshold=0.5,
        passed=True,
        answer="ok",
    )
    with pytest.raises(Exception):  # FrozenInstanceError subclasses AttributeError
        outcome.confidence = 0.0  # type: ignore[misc]
