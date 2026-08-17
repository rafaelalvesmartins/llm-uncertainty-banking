# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :mod:`lub.connectors.bridge.complexity_routed`.

Covers the full Bridge cost-control pipeline: ``ComplexityRouter`` ->
``TierBudget`` -> trimmed ``TieredRouter`` cascade. LLM calls are mocked
via a deterministic ``_FixedPipeline`` test double so the cascade can
be observed for routing decisions, cost accounting, abstention
preservation, and the audit-trail prefix demanded by BCB 4893.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from lub.connectors.bridge.complexity import (
    ComplexityRouter,
    ComplexityTier,
)
from lub.connectors.bridge.complexity_routed import (
    ComplexityRoutedAnswer,
    TierBudget,
)
from lub.orchestration import RouterResult, Tier, TieredRouter
from lub.orchestration.router import ABSTAIN_TIER
from lub.types import UncertaintyResult

# ---------------------------------------------------------------------------
# Test doubles -- mock LLM pipeline that returns a preset confidence.
# ---------------------------------------------------------------------------


@dataclass
class _FixedPipeline:
    """Stand-in for a ``PipelineProto``-conforming LLM backend.

    Returns a deterministic :class:`UncertaintyResult` and tracks call
    count so tests can assert short-circuit / skip behavior.
    """

    confidence: float
    answer_text: str = "fixed"
    calls: int = 0
    received_kwargs: dict[str, Any] | None = None

    def answer(self, prompt: str, **kwargs: Any) -> UncertaintyResult:
        self.calls += 1
        self.received_kwargs = dict(kwargs)
        return UncertaintyResult(answer=self.answer_text, confidence=self.confidence)


@dataclass
class _RaisingPipeline:
    """Pipeline that raises on every call -- used for error-path tests."""

    exc: BaseException
    calls: int = 0

    def answer(self, prompt: str, **kwargs: Any) -> UncertaintyResult:
        self.calls += 1
        raise self.exc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cheap_pipeline() -> _FixedPipeline:
    return _FixedPipeline(confidence=0.95, answer_text="cheap-ans")


@pytest.fixture
def mid_pipeline() -> _FixedPipeline:
    return _FixedPipeline(confidence=0.92, answer_text="mid-ans")


@pytest.fixture
def strong_pipeline() -> _FixedPipeline:
    return _FixedPipeline(confidence=0.99, answer_text="strong-ans")


@pytest.fixture
def three_tier_router(
    cheap_pipeline: _FixedPipeline,
    mid_pipeline: _FixedPipeline,
    strong_pipeline: _FixedPipeline,
) -> TieredRouter:
    return TieredRouter(
        tiers=[
            Tier("haiku", cheap_pipeline, threshold=0.80, cost=0.001),
            Tier("sonnet", mid_pipeline, threshold=0.85, cost=0.010),
            Tier("opus", strong_pipeline, threshold=0.90, cost=0.100),
        ]
    )


@pytest.fixture
def default_routed(three_tier_router: TieredRouter) -> ComplexityRoutedAnswer:
    return ComplexityRoutedAnswer(router=three_tier_router)


# Representative banking prompts: balance/fatura lookups score SIMPLE,
# regulatory jargon (BCB / Basileia) lifts the raw score past the
# medium threshold and triggers COMPLEX routing.
SIMPLE_PROMPT = "qual meu saldo?"
COMPLEX_PROMPT = (
    "Preciso entender como a resolucao BCB 4893 trata o calculo de "
    "Basileia para exposicoes IRPF e qual o impacto no LGPD e KYC "
    "da minha conta empresarial."
)


def _tier_used_in_path(result: RouterResult) -> list[str]:
    """Return the names of tiers that actually ran (excludes the
    complexity-marker entry that this module prepends)."""
    return [e["name"] for e in result.escalation_path if e.get("name") != "complexity"]


# ---------------------------------------------------------------------------
# TierBudget.resolve
# ---------------------------------------------------------------------------


class TestTierBudgetResolve:
    def test_default_simple_only_tier_zero(self) -> None:
        budget = TierBudget()
        assert budget.resolve(ComplexityTier.SIMPLE, total=3) == (0, 0)

    def test_default_medium_skips_cheap_runs_to_end(self) -> None:
        budget = TierBudget()
        assert budget.resolve(ComplexityTier.MEDIUM, total=3) == (1, 2)

    def test_default_complex_only_strongest(self) -> None:
        budget = TierBudget()
        assert budget.resolve(ComplexityTier.COMPLEX, total=3) == (2, 2)

    def test_negative_index_wraps_from_end(self) -> None:
        budget = TierBudget(simple_start=-2, simple_end=-1)
        assert budget.resolve(ComplexityTier.SIMPLE, total=4) == (2, 3)

    def test_out_of_range_clamps(self) -> None:
        budget = TierBudget(complex_start=10, complex_end=20)
        # Only one tier => everything clamps to 0.
        assert budget.resolve(ComplexityTier.COMPLEX, total=1) == (0, 0)

    def test_inverted_range_is_swapped(self) -> None:
        budget = TierBudget(simple_start=2, simple_end=0)
        assert budget.resolve(ComplexityTier.SIMPLE, total=3) == (0, 2)

    def test_single_tier_cascade_collapses_medium_gracefully(self) -> None:
        # Default MEDIUM is (1, -1). With one tier, both ends clamp to 0,
        # so MEDIUM degenerates to "use the only tier available" rather
        # than producing an empty slice.
        budget = TierBudget()
        assert budget.resolve(ComplexityTier.MEDIUM, total=1) == (0, 0)

    def test_empty_cascade_raises(self) -> None:
        budget = TierBudget()
        with pytest.raises(ValueError, match="empty cascade"):
            budget.resolve(ComplexityTier.SIMPLE, total=0)

    def test_dataclass_is_frozen(self) -> None:
        budget = TierBudget()
        with pytest.raises(AttributeError):
            budget.simple_start = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ComplexityRoutedAnswer construction
# ---------------------------------------------------------------------------


class TestComplexityRoutedAnswerConstruction:
    def test_rejects_non_router(self) -> None:
        with pytest.raises(TypeError, match="TieredRouter"):
            ComplexityRoutedAnswer(router="not-a-router")  # type: ignore[arg-type]

    def test_rejects_non_complexity_router(
        self, three_tier_router: TieredRouter
    ) -> None:
        with pytest.raises(TypeError, match="ComplexityRouter"):
            ComplexityRoutedAnswer(
                router=three_tier_router,
                complexity="nope",  # type: ignore[arg-type]
            )

    def test_rejects_non_budget(self, three_tier_router: TieredRouter) -> None:
        with pytest.raises(TypeError, match="TierBudget"):
            ComplexityRoutedAnswer(
                router=three_tier_router,
                budget={"simple_start": 0},  # type: ignore[arg-type]
            )

    def test_rejects_router_with_no_tiers(self) -> None:
        # TieredRouter already rejects empty tiers at construction; build a
        # router then strip its tiers to hit the wrapper's own check.
        pipe = _FixedPipeline(confidence=0.9)
        router = TieredRouter(tiers=[Tier("t", pipe, 0.5)])
        router.tiers = []
        with pytest.raises(ValueError, match="no tiers"):
            ComplexityRoutedAnswer(router=router)

    def test_defaults_applied(self, three_tier_router: TieredRouter) -> None:
        routed = ComplexityRoutedAnswer(router=three_tier_router)
        assert isinstance(routed.complexity, ComplexityRouter)
        assert isinstance(routed.budget, TierBudget)


# ---------------------------------------------------------------------------
# Routing behavior -- the core of the cost-control invariant.
# ---------------------------------------------------------------------------


class TestRoutingBehavior:
    def test_simple_query_uses_only_cheap_tier(
        self,
        default_routed: ComplexityRoutedAnswer,
        cheap_pipeline: _FixedPipeline,
        mid_pipeline: _FixedPipeline,
        strong_pipeline: _FixedPipeline,
    ) -> None:
        result = default_routed.answer(SIMPLE_PROMPT)

        assert cheap_pipeline.calls == 1
        assert mid_pipeline.calls == 0
        assert strong_pipeline.calls == 0
        assert result.tier_used == "haiku"
        assert result.final.answer == "cheap-ans"
        assert result.total_cost == pytest.approx(0.001)

    def test_complex_query_jumps_to_strongest_tier(
        self,
        default_routed: ComplexityRoutedAnswer,
        cheap_pipeline: _FixedPipeline,
        mid_pipeline: _FixedPipeline,
        strong_pipeline: _FixedPipeline,
    ) -> None:
        result = default_routed.answer(COMPLEX_PROMPT)

        # Cheap/mid never run -- regulatory questions skip the warm-up.
        assert cheap_pipeline.calls == 0
        assert mid_pipeline.calls == 0
        assert strong_pipeline.calls == 1
        assert result.tier_used == "opus"
        assert result.final.answer == "strong-ans"
        assert result.total_cost == pytest.approx(0.100)

    def test_medium_query_skips_cheap_tier(
        self,
        cheap_pipeline: _FixedPipeline,
        mid_pipeline: _FixedPipeline,
        strong_pipeline: _FixedPipeline,
        three_tier_router: TieredRouter,
    ) -> None:
        # Tune the complexity router so this prompt scores MEDIUM and
        # avoid relying on the default heuristic landing the prompt on a
        # specific tier.
        complexity = ComplexityRouter()
        prompt = "se eu pagar uma fatura agora, vai compensar no mesmo dia?"
        score = complexity.score(prompt)
        assert score.tier is ComplexityTier.MEDIUM, (
            f"precondition: expected MEDIUM, got {score.tier} (rationale={score.rationale})"
        )

        routed = ComplexityRoutedAnswer(router=three_tier_router, complexity=complexity)
        result = routed.answer(prompt)

        assert cheap_pipeline.calls == 0
        assert mid_pipeline.calls == 1
        # Mid pipeline confidence 0.92 >= threshold 0.85, so strong is skipped.
        assert strong_pipeline.calls == 0
        assert result.tier_used == "sonnet"

    def test_kwargs_passed_through_to_pipeline(
        self,
        default_routed: ComplexityRoutedAnswer,
        cheap_pipeline: _FixedPipeline,
    ) -> None:
        default_routed.answer(SIMPLE_PROMPT, customer_id="C-42", trace_id="t-1")
        assert cheap_pipeline.received_kwargs == {
            "customer_id": "C-42",
            "trace_id": "t-1",
        }


# ---------------------------------------------------------------------------
# Confidence / abstention -- the SR 11-7 invariant.
# ---------------------------------------------------------------------------


class TestConfidenceAndAbstention:
    def test_low_confidence_in_trimmed_slice_abstains(
        self, three_tier_router: TieredRouter
    ) -> None:
        # Swap in a low-confidence opus so the COMPLEX-only slice fails
        # its threshold. The wrapper must NOT silently expand back to
        # cheap/mid -- abstention propagates.
        weak_opus = _FixedPipeline(confidence=0.10, answer_text="weak-opus")
        three_tier_router.tiers[2] = Tier("opus", weak_opus, threshold=0.90, cost=0.100)

        routed = ComplexityRoutedAnswer(router=three_tier_router)
        result = routed.answer(COMPLEX_PROMPT)

        assert result.tier_used == ABSTAIN_TIER
        assert result.final.should_refuse is True
        # Cost still reflects the one expensive call we did make.
        assert result.total_cost == pytest.approx(0.100)
        # Cheap/mid were NOT invoked as a fallback -- that would silently
        # relax the safety guarantee.
        cheap_pipe = three_tier_router.tiers[0].pipeline
        mid_pipe = three_tier_router.tiers[1].pipeline
        assert cheap_pipe.calls == 0  # type: ignore[attr-defined]
        assert mid_pipe.calls == 0  # type: ignore[attr-defined]

    def test_high_confidence_passes_through(
        self,
        default_routed: ComplexityRoutedAnswer,
    ) -> None:
        result = default_routed.answer(SIMPLE_PROMPT)
        assert result.final.should_refuse is False
        assert result.tier_used == "haiku"

    def test_escalation_within_slice_when_first_tier_low(
        self,
        cheap_pipeline: _FixedPipeline,
        mid_pipeline: _FixedPipeline,
        strong_pipeline: _FixedPipeline,
    ) -> None:
        # Mid below threshold; strong above. With MEDIUM budget (tiers
        # 1..end) the cascade should escalate within the slice from
        # sonnet to opus.
        mid_pipeline.confidence = 0.40
        router = TieredRouter(
            tiers=[
                Tier("haiku", cheap_pipeline, 0.80, 0.001),
                Tier("sonnet", mid_pipeline, 0.85, 0.010),
                Tier("opus", strong_pipeline, 0.90, 0.100),
            ]
        )
        # Tune thresholds so any non-trivial prompt scores MEDIUM. Below
        # the prompt has >5 words => raw_score 0.5, which clears
        # simple_threshold (0.1) but stays well under medium_threshold
        # (100.0), landing MEDIUM regardless of jargon heuristics.
        complexity = ComplexityRouter(simple_threshold=0.1, medium_threshold=100.0)
        routed = ComplexityRoutedAnswer(router=router, complexity=complexity)

        prompt = "tenho uma duvida sobre o pagamento da fatura"
        precond = complexity.score(prompt)
        assert precond.tier is ComplexityTier.MEDIUM, (
            f"precondition: expected MEDIUM, got {precond.tier} (raw={precond.raw_score})"
        )
        result = routed.answer(prompt)

        assert cheap_pipeline.calls == 0  # cheap excluded by MEDIUM budget
        assert mid_pipeline.calls == 1
        assert strong_pipeline.calls == 1
        assert result.tier_used == "opus"
        assert result.total_cost == pytest.approx(0.110)


# ---------------------------------------------------------------------------
# Audit-trail / BCB 4893 -- the complexity-marker entry.
# ---------------------------------------------------------------------------


class TestAuditTrail:
    def test_complexity_marker_prepended(
        self,
        default_routed: ComplexityRoutedAnswer,
    ) -> None:
        result = default_routed.answer(COMPLEX_PROMPT)

        assert result.escalation_path[0]["name"] == "complexity"
        marker = result.escalation_path[0]
        assert marker["complexity_tier"] == ComplexityTier.COMPLEX.value
        assert isinstance(marker["raw_score"], float)
        assert marker["slice_start"] == 2
        assert marker["slice_end"] == 2
        assert marker["trimmed_tier_names"] == ["opus"]
        assert "regulatory" in marker["rationale"]

    def test_per_tier_entries_follow_marker(
        self,
        default_routed: ComplexityRoutedAnswer,
    ) -> None:
        result = default_routed.answer(SIMPLE_PROMPT)
        names = [e["name"] for e in result.escalation_path]
        assert names == ["complexity", "haiku"]
        assert result.escalation_path[1]["passed"] is True


# ---------------------------------------------------------------------------
# Non-mutation -- debug surfaces and replays rely on the original router.
# ---------------------------------------------------------------------------


class TestNonMutation:
    def test_underlying_router_tiers_unchanged(
        self,
        default_routed: ComplexityRoutedAnswer,
        three_tier_router: TieredRouter,
    ) -> None:
        original = list(three_tier_router.tiers)
        default_routed.answer(COMPLEX_PROMPT)
        default_routed.answer(SIMPLE_PROMPT)
        assert three_tier_router.tiers == original
        assert len(three_tier_router.tiers) == 3

    def test_repeated_calls_independent(
        self,
        default_routed: ComplexityRoutedAnswer,
        cheap_pipeline: _FixedPipeline,
        strong_pipeline: _FixedPipeline,
    ) -> None:
        default_routed.answer(SIMPLE_PROMPT)
        default_routed.answer(COMPLEX_PROMPT)
        assert cheap_pipeline.calls == 1
        assert strong_pipeline.calls == 1


# ---------------------------------------------------------------------------
# Edge cases -- empty input, single-tier cascade, custom budget.
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_prompt_still_routes(
        self,
        default_routed: ComplexityRoutedAnswer,
        cheap_pipeline: _FixedPipeline,
    ) -> None:
        result = default_routed.answer("")
        # Empty prompt scores 0 -> SIMPLE -> tier 0 only.
        assert cheap_pipeline.calls == 1
        assert result.tier_used == "haiku"
        assert result.escalation_path[0]["complexity_tier"] == ComplexityTier.SIMPLE.value

    def test_whitespace_only_prompt(
        self,
        default_routed: ComplexityRoutedAnswer,
        cheap_pipeline: _FixedPipeline,
    ) -> None:
        result = default_routed.answer("   \n\t  ")
        assert cheap_pipeline.calls == 1
        assert result.tier_used == "haiku"

    def test_single_tier_cascade(self) -> None:
        only_pipe = _FixedPipeline(confidence=0.95, answer_text="only")
        router = TieredRouter(tiers=[Tier("solo", only_pipe, 0.5, 0.001)])
        routed = ComplexityRoutedAnswer(router=router)

        # Both SIMPLE and COMPLEX paths must collapse to the only tier.
        simple = routed.answer(SIMPLE_PROMPT)
        complex_ = routed.answer(COMPLEX_PROMPT)

        assert simple.tier_used == "solo"
        assert complex_.tier_used == "solo"
        assert only_pipe.calls == 2

    def test_custom_budget_overrides_defaults(
        self,
        three_tier_router: TieredRouter,
        cheap_pipeline: _FixedPipeline,
        strong_pipeline: _FixedPipeline,
    ) -> None:
        # Promote SIMPLE to also use tier 2 (override default).
        budget = TierBudget(simple_start=0, simple_end=-1)
        routed = ComplexityRoutedAnswer(router=three_tier_router, budget=budget)
        result = routed.answer(SIMPLE_PROMPT)
        # Cheap clears at 0.95 >= 0.80, so strong never runs even though it's eligible.
        assert cheap_pipeline.calls == 1
        assert strong_pipeline.calls == 0
        assert result.tier_used == "haiku"

    def test_digit_heavy_prompt_invalid_amount_still_routes(
        self,
        default_routed: ComplexityRoutedAnswer,
        cheap_pipeline: _FixedPipeline,
    ) -> None:
        # Garbage amount -- the wrapper does not validate banking
        # semantics; it just routes. Downstream guard/agent owns refusal.
        result = default_routed.answer("transferir -99999999.99 para 000000000")
        assert cheap_pipeline.calls >= 1
        assert result.final is not None

    def test_pii_prompt_passes_through_unmodified(
        self,
        default_routed: ComplexityRoutedAnswer,
        three_tier_router: TieredRouter,
    ) -> None:
        # PII redaction is NOT this wrapper's job -- it must not silently
        # alter the prompt. The wrapper simply scores and routes. Use a
        # PII string without sentence-splitting punctuation so the score
        # is dominated by length, not by dot-splitting artifacts.
        pii_prompt = "saldo do CPF 12345678909"
        result = default_routed.answer(pii_prompt)
        # Some tier ran -- whichever tier the complexity score selected.
        assert sum(t.pipeline.calls for t in three_tier_router.tiers) >= 1  # type: ignore[attr-defined]
        assert result.escalation_path[0]["name"] == "complexity"


# ---------------------------------------------------------------------------
# Error handling -- backend failures propagate from the scoped router.
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_pipeline_timeout_propagates(
        self,
        three_tier_router: TieredRouter,
    ) -> None:
        # Make the strongest tier fail. COMPLEX_PROMPT routes only there,
        # so the timeout surfaces immediately.
        three_tier_router.tiers[2] = Tier(
            "opus",
            _RaisingPipeline(exc=TimeoutError("backend timeout")),
            threshold=0.90,
            cost=0.100,
        )
        routed = ComplexityRoutedAnswer(router=three_tier_router)

        with pytest.raises(TimeoutError, match="backend timeout"):
            routed.answer(COMPLEX_PROMPT)

    def test_invalid_confidence_in_response_propagates(
        self,
        three_tier_router: TieredRouter,
    ) -> None:
        # Pipeline returns a malformed result -- UncertaintyResult validates
        # confidence in [0, 1], so the bad value raises before reaching the
        # router. The wrapper must not swallow it.
        class _BadPipeline:
            calls = 0

            def answer(self, prompt: str, **kwargs: Any) -> UncertaintyResult:
                self.calls += 1
                return UncertaintyResult(answer="x", confidence=1.5)

        three_tier_router.tiers[0] = Tier("haiku", _BadPipeline(), 0.80, 0.001)
        routed = ComplexityRoutedAnswer(router=three_tier_router)

        with pytest.raises(ValueError, match="confidence"):
            routed.answer(SIMPLE_PROMPT)

    def test_non_transient_value_error_propagates(
        self,
        three_tier_router: TieredRouter,
    ) -> None:
        # Confirms calibration-layer / programmer errors are not masked
        # by silently expanding the slice.
        three_tier_router.tiers[0] = Tier(
            "haiku",
            _RaisingPipeline(exc=ValueError("calibration bug")),
            threshold=0.80,
            cost=0.001,
        )
        routed = ComplexityRoutedAnswer(router=three_tier_router)

        with pytest.raises(ValueError, match="calibration bug"):
            routed.answer(SIMPLE_PROMPT)


# ---------------------------------------------------------------------------
# Static helper -- _complexity_audit_event.
# ---------------------------------------------------------------------------


class TestComplexityAuditEvent:
    def test_event_shape_is_jsonable(self) -> None:
        complexity = ComplexityRouter()
        score = complexity.score(COMPLEX_PROMPT)
        pipe = _FixedPipeline(confidence=0.9)
        tiers = [Tier("a", pipe, 0.5), Tier("b", pipe, 0.5)]
        event = ComplexityRoutedAnswer._complexity_audit_event(
            score=score, start=0, end=1, trimmed=tiers
        )
        # All values must be primitive/JSON-friendly.
        assert event["name"] == "complexity"
        assert event["complexity_tier"] == score.tier.value
        assert isinstance(event["raw_score"], float)
        assert isinstance(event["rationale"], str)
        assert event["slice_start"] == 0
        assert event["slice_end"] == 1
        assert event["trimmed_tier_names"] == ["a", "b"]
