# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for the lightweight rails hook layer."""

from __future__ import annotations

import pytest

from lub.pipeline import UncertaintyPipeline
from lub.rails import (
    InputRailRejected,
    OutputRailRejected,
    RailSet,
    force_refuse_below,
    max_length,
    reject_pii,
    require_confidence,
    strip_chain_of_thought,
    strip_whitespace,
)
from lub.types import UncertaintyResult


def _result(confidence: float, answer: str = "ans") -> UncertaintyResult:
    return UncertaintyResult(
        answer=answer,
        confidence=confidence,
        raw_scores={},
        samples=None,
        should_refuse=False,
    )


# ---- input rails ----------------------------------------------------------


def test_max_length_accepts_short_prompt() -> None:
    rail = max_length(100)
    assert rail("hello") == "hello"


def test_max_length_rejects_long_prompt() -> None:
    rail = max_length(4)
    with pytest.raises(InputRailRejected):
        rail("hello")


def test_max_length_invalid_config() -> None:
    with pytest.raises(ValueError):
        max_length(0)


def test_reject_pii_email() -> None:
    rail = reject_pii()
    with pytest.raises(InputRailRejected, match="email"):
        rail("Contact me at user@example.com please")


def test_reject_pii_cpf() -> None:
    rail = reject_pii()
    with pytest.raises(InputRailRejected, match="cpf"):
        rail("CPF 123.456.789-00")


def test_reject_pii_category_filter() -> None:
    # Only email is active; SSN-looking content should pass
    rail = reject_pii(categories=("email",))
    assert rail("SSN 123-45-6789") == "SSN 123-45-6789"


def test_strip_whitespace() -> None:
    rail = strip_whitespace()
    assert rail("   hello world   ") == "hello world"


# ---- output rails ---------------------------------------------------------


def test_require_confidence_passes() -> None:
    rail = require_confidence(0.3)
    out = rail(_result(0.5))
    assert out.confidence == 0.5


def test_require_confidence_rejects() -> None:
    rail = require_confidence(0.6)
    with pytest.raises(OutputRailRejected):
        rail(_result(0.5))


def test_require_confidence_invalid_config() -> None:
    with pytest.raises(ValueError):
        require_confidence(1.5)


def test_strip_chain_of_thought() -> None:
    rail = strip_chain_of_thought("Let's think step by step")
    r = _result(0.9, answer="Answer: 42. Let's think step by step: reasoning...")
    out = rail(r)
    assert out.answer == "Answer: 42."


def test_force_refuse_below() -> None:
    rail = force_refuse_below(0.5)
    out = rail(_result(0.4))
    assert out.should_refuse is True
    out2 = rail(_result(0.9))
    assert out2.should_refuse is False


def test_force_refuse_below_invalid_config() -> None:
    with pytest.raises(ValueError):
        force_refuse_below(-0.1)


# ---- RailSet integration ---------------------------------------------------


def test_rail_set_applies_input_and_output_in_order() -> None:
    rs = RailSet(
        input_rails=(strip_whitespace(), max_length(20)),
        output_rails=(require_confidence(0.3),),
    )
    assert rs.apply_input("  hello  ") == "hello"
    out = rs.apply_output(_result(0.5))
    assert out.confidence == 0.5


def test_pipeline_honors_rails_on_answer() -> None:
    pipe = UncertaintyPipeline.from_pretrained(
        model="dummy-model",
        backend="dummy",
        estimator="self_consistency",
        n_samples=4,
        rails=RailSet(
            input_rails=(max_length(200),),
            output_rails=(force_refuse_below(0.99),),
        ),
    )
    result = pipe.answer("short prompt")
    # force_refuse_below(0.99) flips the refuse flag for anything < 0.99
    assert result.should_refuse is True


def test_pipeline_rail_rejection_propagates() -> None:
    pipe = UncertaintyPipeline.from_pretrained(
        model="dummy-model",
        backend="dummy",
        estimator="token_logprob",
        rails=RailSet(input_rails=(max_length(3),)),
    )
    with pytest.raises(InputRailRejected):
        pipe.answer("this prompt is definitely too long")
