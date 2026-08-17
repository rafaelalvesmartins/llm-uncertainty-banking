# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""PolicyDecision.REASK tests."""

from __future__ import annotations

from lub.policies import PolicyDecision, rmf_subcategory


def test_reask_is_policy_decision_member() -> None:
    assert PolicyDecision.REASK.value == "reask"
    assert PolicyDecision.REASK in PolicyDecision


def test_reask_maps_to_manage_2_4() -> None:
    assert rmf_subcategory(PolicyDecision.REASK) == "MANAGE 2.4"


def test_reask_value_survives_json_round_trip() -> None:
    import json
    v = json.dumps({"decision": PolicyDecision.REASK.value})
    loaded = json.loads(v)
    assert loaded["decision"] == "reask"
    assert PolicyDecision(loaded["decision"]) is PolicyDecision.REASK
