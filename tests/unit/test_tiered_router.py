# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from lub.orchestration.router import ABSTAIN_TIER, RouterResult, Tier, TieredRouter
from lub.types import UncertaintyResult


@dataclass
class _FixedPipeline:
    """Test double that returns a preset UncertaintyResult."""

    confidence: float
    _answer_text: str = "fixed"
    calls: int = 0

    def answer_call(self, prompt: str, **kwargs: Any) -> UncertaintyResult:
        return UncertaintyResult(answer=self._answer_text, confidence=self.confidence)

    def answer(self, prompt: str, **kwargs: Any) -> UncertaintyResult:  # protocol
        self.calls += 1
        return self.answer_call(prompt, **kwargs)


def test_first_tier_passes_short_circuits() -> None:
    cheap = _FixedPipeline(confidence=0.9, _answer_text="cheap-ans")
    strong = _FixedPipeline(confidence=0.99, _answer_text="strong-ans")
    router = TieredRouter(
        tiers=[
            Tier("cheap", cheap, threshold=0.8, cost=0.001),
            Tier("strong", strong, threshold=0.9, cost=0.010),
        ]
    )
    out: RouterResult = router.answer("x")
    assert out.tier_used == "cheap"
    assert out.final.answer == "cheap-ans"
    assert out.total_cost == pytest.approx(0.001)
    assert strong.calls == 0  # short-circuited
    assert len(out.escalation_path) == 1


def test_escalates_to_strong_tier() -> None:
    cheap = _FixedPipeline(confidence=0.5, _answer_text="cheap-ans")
    strong = _FixedPipeline(confidence=0.95, _answer_text="strong-ans")
    router = TieredRouter(
        tiers=[
            Tier("cheap", cheap, threshold=0.8, cost=0.001),
            Tier("strong", strong, threshold=0.9, cost=0.010),
        ]
    )
    out = router.answer("x")
    assert out.tier_used == "strong"
    assert out.final.answer == "strong-ans"
    assert out.total_cost == pytest.approx(0.011)
    assert len(out.escalation_path) == 2


def test_abstains_when_no_tier_clears() -> None:
    t1 = _FixedPipeline(confidence=0.2, _answer_text="a1")
    t2 = _FixedPipeline(confidence=0.4, _answer_text="a2")
    router = TieredRouter(
        tiers=[Tier("t1", t1, 0.9, 0.01), Tier("t2", t2, 0.9, 0.02)]
    )
    out = router.answer("x")
    assert out.tier_used == ABSTAIN_TIER
    assert out.final.should_refuse is True
    assert out.total_cost == pytest.approx(0.03)
    # escalation_path has both tiers, neither passed
    assert [p["passed"] for p in out.escalation_path] == [False, False]


def test_router_rejects_empty_tiers() -> None:
    with pytest.raises(ValueError, match="at least one tier"):
        TieredRouter(tiers=[])


def test_router_rejects_duplicate_tier_names() -> None:
    t = _FixedPipeline(confidence=0.5)
    with pytest.raises(ValueError, match="unique"):
        TieredRouter(tiers=[Tier("x", t, 0.5), Tier("x", t, 0.5)])


def test_tier_validates_threshold() -> None:
    t = _FixedPipeline(confidence=0.5)
    with pytest.raises(ValueError, match="threshold"):
        Tier("bad", t, threshold=1.5)


def test_tier_validates_cost_nonnegative() -> None:
    t = _FixedPipeline(confidence=0.5)
    with pytest.raises(ValueError, match="cost"):
        Tier("bad", t, threshold=0.5, cost=-0.1)


def test_batch_preserves_order() -> None:
    t = _FixedPipeline(confidence=0.9)
    router = TieredRouter(tiers=[Tier("only", t, 0.8, 0.001)])
    out = router.batch(["a", "b", "c"])
    assert len(out) == 3
    assert all(isinstance(r, RouterResult) for r in out)


def test_to_dict_is_json_safe() -> None:
    t = _FixedPipeline(confidence=0.9)
    router = TieredRouter(tiers=[Tier("only", t, 0.8, 0.001)])
    d = router.answer("x").to_dict()
    import json

    json.dumps(d)  # must not raise
    assert d["tier_used"] == "only"
