# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""ESCALATE policy: hand a low-confidence prompt to a stronger pipeline.

REASK retries the *same* pipeline with a corrective prefix. ESCALATE
retries a *different, stronger* pipeline — the deferral half of
selective prediction. When the stronger tier also falls short, the
guard abstains and marks the call for human review, carrying both
drafts so the reviewer does not start from zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from lub.guard import PolicyDecision, UncertaintyGuard, rmf_subcategory
from lub.types import UncertaintyResult


@dataclass
class _FixedPipeline:
    """Pipeline double returning a preset confidence; counts its calls."""

    confidence: float
    answer_text: str = "fixed"
    calls: list[str] = field(default_factory=list)

    def answer(self, prompt: str, **kwargs: Any) -> UncertaintyResult:
        self.calls.append(prompt)
        return UncertaintyResult(answer=self.answer_text, confidence=self.confidence)


# --- vocabulary -------------------------------------------------------------


def test_escalate_is_a_policy_decision() -> None:
    assert PolicyDecision.ESCALATE.value == "escalate"


def test_escalate_has_an_rmf_subcategory() -> None:
    # Escalation supersedes the model's own output with a stronger system
    # or a human — the MANAGE 2.4 "supersede / disengage" family.
    assert rmf_subcategory(PolicyDecision.ESCALATE) == "MANAGE 2.4"


# --- happy path -------------------------------------------------------------


def test_low_confidence_escalates_and_returns_the_stronger_answer() -> None:
    weak = _FixedPipeline(confidence=0.34, answer_text="weak-answer")
    strong = _FixedPipeline(confidence=0.81, answer_text="strong-answer")
    guard = UncertaintyGuard(
        weak,
        threshold=0.70,
        on_fail=PolicyDecision.ESCALATE,
        escalate_to=strong,
    )

    result = guard("posso antecipar meu 13o pelo app?")

    assert result.outcome.decision is PolicyDecision.ESCALATE
    assert result.output == "strong-answer"
    assert result.outcome.passed is True
    assert len(strong.calls) == 1


def test_high_confidence_never_calls_the_escalation_tier() -> None:
    """Cost control: the expensive tier must stay idle on easy prompts."""
    weak = _FixedPipeline(confidence=0.95, answer_text="weak-answer")
    strong = _FixedPipeline(confidence=0.99, answer_text="strong-answer")
    guard = UncertaintyGuard(
        weak,
        threshold=0.70,
        on_fail=PolicyDecision.ESCALATE,
        escalate_to=strong,
    )

    result = guard("qual meu saldo?")

    assert result.outcome.decision is PolicyDecision.PASSTHROUGH
    assert result.output == "weak-answer"
    assert strong.calls == []


def test_escalation_records_both_confidences_for_audit() -> None:
    weak = _FixedPipeline(confidence=0.34, answer_text="weak-answer")
    strong = _FixedPipeline(confidence=0.81, answer_text="strong-answer")
    guard = UncertaintyGuard(
        weak,
        threshold=0.70,
        on_fail=PolicyDecision.ESCALATE,
        escalate_to=strong,
        escalate_to_name="tier2-local",
    )

    meta = guard("pergunta dificil").outcome.metadata

    assert meta["first_pass_confidence"] == pytest.approx(0.34)
    assert meta["escalation_attempted"] is True
    assert meta["escalation_succeeded"] is True
    assert meta["escalated_to"] == "tier2-local"


def test_escalation_reuses_the_original_prompt_verbatim() -> None:
    """Unlike REASK, escalation must not mutate the customer's question."""
    weak = _FixedPipeline(confidence=0.10)
    strong = _FixedPipeline(confidence=0.90)
    guard = UncertaintyGuard(
        weak, threshold=0.70, on_fail=PolicyDecision.ESCALATE, escalate_to=strong
    )

    guard("qual a taxa do CDB?")

    assert strong.calls == ["qual a taxa do CDB?"]


# --- human handoff ----------------------------------------------------------


def test_both_tiers_below_threshold_falls_through_to_abstain() -> None:
    weak = _FixedPipeline(confidence=0.20, answer_text="weak-answer")
    strong = _FixedPipeline(confidence=0.45, answer_text="strong-answer")
    guard = UncertaintyGuard(
        weak, threshold=0.70, on_fail=PolicyDecision.ESCALATE, escalate_to=strong
    )

    result = guard("pergunta impossivel")

    assert result.outcome.decision is PolicyDecision.ABSTAIN
    assert result.outcome.passed is False
    assert result.outcome.metadata["escalation_succeeded"] is False


def test_human_review_package_carries_both_drafts() -> None:
    """A human picking this up must see what each tier actually said."""
    weak = _FixedPipeline(confidence=0.20, answer_text="weak-answer")
    strong = _FixedPipeline(confidence=0.45, answer_text="strong-answer")
    guard = UncertaintyGuard(
        weak, threshold=0.70, on_fail=PolicyDecision.ESCALATE, escalate_to=strong
    )

    meta = guard("pergunta impossivel").outcome.metadata

    assert meta["human_review_required"] is True
    assert meta["primary_answer"] == "weak-answer"
    assert meta["escalation_answer"] == "strong-answer"
    assert meta["first_pass_confidence"] == pytest.approx(0.20)


# --- fail-closed configuration ---------------------------------------------


def test_escalate_without_a_target_is_rejected_at_construction() -> None:
    """Fail closed: an ESCALATE policy with nowhere to escalate is a config bug."""
    weak = _FixedPipeline(confidence=0.34)

    with pytest.raises(ValueError, match="escalate_to"):
        UncertaintyGuard(weak, threshold=0.70, on_fail=PolicyDecision.ESCALATE)


def test_escalate_to_is_ignored_by_other_policies() -> None:
    """Configuring a target without the ESCALATE policy must not silently route."""
    weak = _FixedPipeline(confidence=0.34, answer_text="weak-answer")
    strong = _FixedPipeline(confidence=0.99, answer_text="strong-answer")
    guard = UncertaintyGuard(
        weak, threshold=0.70, on_fail=PolicyDecision.ABSTAIN, escalate_to=strong
    )

    result = guard("pergunta")

    assert result.outcome.decision is PolicyDecision.ABSTAIN
    assert strong.calls == []
