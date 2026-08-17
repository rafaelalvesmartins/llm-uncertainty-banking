# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for :mod:`lub.connectors.bridge.answer_scorer`.

The answer scorer closes a real calibration gap in Bridge: confidence
returned by :class:`UncertaintyGuard` was attributed to *its* pipeline
answer, not the agent's answer. These tests pin the post-hoc rescoring
contract — confidence must be a function of the agent's actual text —
plus the gating semantics (PASSTHROUGH ≥ threshold, ABSTAIN otherwise),
edge-case handling (empty input, unicode, sampler failures), and the
shape of audit-trail metadata that the BCB 4893 reporter consumes.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import pytest

from lub.connectors.bridge.answer_scorer import (
    DEFAULT_ABSTAIN_MARKER,
    DEFAULT_VERIFIER_TEMPLATE,
    AnswerScorer,
    CompositeAnswerScorer,
    LexicalConsistencyScorer,
    PTrueScorer,
    _jaccard,
    _parse_p_true,
    _tokenize,
    gate_answer_score,
)
from lub.guard import GuardResult, PolicyDecision, rmf_subcategory
from lub.types import UncertaintyResult

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_sampler(replies: list[str]) -> Callable[[str], str]:
    """Build a deterministic sampler that pops fixed replies in order."""
    queue = list(replies)

    def _sampler(_prompt: str) -> str:
        if not queue:
            raise RuntimeError("sampler exhausted")
        return queue.pop(0)

    return _sampler


def _flaky_sampler(replies_then_error: list[str | Exception]) -> Callable[[str], str]:
    """Build a sampler that interleaves valid replies and exceptions."""
    queue = list(replies_then_error)

    def _sampler(_prompt: str) -> str:
        if not queue:
            raise RuntimeError("sampler exhausted")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return _sampler


class _FixedScorer:
    """Deterministic AnswerScorer for composite tests."""

    def __init__(
        self,
        confidence: float,
        *,
        should_refuse: bool = False,
        raw_scores: dict[str, float] | None = None,
    ) -> None:
        self.confidence = confidence
        self.should_refuse = should_refuse
        self.raw_scores = raw_scores or {}
        self.calls: list[tuple[str, str]] = []

    def score(self, prompt: str, answer: str) -> UncertaintyResult:
        self.calls.append((prompt, answer))
        return UncertaintyResult(
            answer=answer,
            confidence=self.confidence,
            raw_scores=dict(self.raw_scores),
            should_refuse=self.should_refuse,
        )


@pytest.fixture
def banking_prompt() -> str:
    return "Qual a taxa do CDB pré-fixado de 12 meses no Bradesco?"


@pytest.fixture
def banking_answer() -> str:
    return "A taxa atual do CDB pré-fixado de 12 meses é de 11.5% ao ano."


# ---------------------------------------------------------------------------
# _tokenize / _jaccard
# ---------------------------------------------------------------------------


class TestTokenization:
    def test_tokenize_case_folds_and_splits_words(self) -> None:
        tokens = _tokenize("Bradesco PIX Taxa")
        assert tokens == {"bradesco", "pix", "taxa"}

    def test_tokenize_handles_unicode_and_punctuation(self) -> None:
        # Portuguese accents are word chars under re.UNICODE
        tokens = _tokenize("Não é correto, está errado!")
        assert "não" in tokens
        assert "está" in tokens
        assert "errado" in tokens

    def test_tokenize_empty_string_is_empty_set(self) -> None:
        assert _tokenize("") == set()

    def test_tokenize_whitespace_only_is_empty_set(self) -> None:
        assert _tokenize("   \n\t  ") == set()

    def test_jaccard_identical_sets(self) -> None:
        assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_jaccard_disjoint_sets(self) -> None:
        assert _jaccard({"a"}, {"b"}) == 0.0

    def test_jaccard_partial_overlap(self) -> None:
        # |intersection|=1, |union|=3
        assert _jaccard({"a", "b"}, {"a", "c"}) == pytest.approx(1 / 3)

    def test_jaccard_two_empty_sets_treated_as_perfect_match(self) -> None:
        # Defensive: avoids ZeroDivision on empty answers
        assert _jaccard(set(), set()) == 1.0

    def test_jaccard_empty_vs_nonempty_is_zero(self) -> None:
        assert _jaccard(set(), {"a"}) == 0.0


# ---------------------------------------------------------------------------
# _parse_p_true
# ---------------------------------------------------------------------------


class TestParsePTrue:
    @pytest.mark.parametrize(
        "reply",
        ["yes", "YES", "Yes, the answer is correct", "true", "Correct.", "Right!"],
    )
    def test_english_true_tokens_yield_one(self, reply: str) -> None:
        assert _parse_p_true(reply) == 1.0

    @pytest.mark.parametrize("reply", ["no", "No.", "false", "Wrong answer"])
    def test_english_false_tokens_yield_zero(self, reply: str) -> None:
        assert _parse_p_true(reply) == 0.0

    @pytest.mark.parametrize("reply", ["sim", "Sim, está correto", "verdadeiro"])
    def test_portuguese_true_tokens_yield_one(self, reply: str) -> None:
        # Bradesco serves a PT-BR customer base; both "correto" and "sim"
        # vote True so the result stays at 1.0.
        assert _parse_p_true(reply) == 1.0

    @pytest.mark.parametrize("reply", ["não", "nao", "falso", "errado"])
    def test_portuguese_false_tokens_yield_zero(self, reply: str) -> None:
        assert _parse_p_true(reply) == 0.0

    def test_substring_collision_incorrect_counts_both(self) -> None:
        # "incorrect" contains "correct" — parser uses substring matching,
        # so this naturally splits 1 true / 1 false → 0.5. Pinning this
        # so a future tokenization-based rewrite has to confront the change.
        assert _parse_p_true("incorrect") == 0.5
        assert _parse_p_true("incorreto") == 0.5

    def test_ambiguous_reply_returns_one_half(self) -> None:
        # No keywords on either side -> maximally uncertain
        assert _parse_p_true("hmm, talvez, depends on context") == 0.5

    def test_empty_reply_returns_one_half(self) -> None:
        assert _parse_p_true("") == 0.5

    def test_mixed_signals_average(self) -> None:
        # "yes" and "no" both present -> 1/2
        assert _parse_p_true("well, yes but also no") == 0.5

    def test_two_true_one_false(self) -> None:
        # yes + correct = 2 true; no = 1 false -> 2/3
        assert _parse_p_true("yes, correct, but no edge case") == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# LexicalConsistencyScorer
# ---------------------------------------------------------------------------


class TestLexicalConsistencyScorer:
    def test_construction_rejects_zero_n_samples(self) -> None:
        with pytest.raises(ValueError, match="n_samples must be >= 1"):
            LexicalConsistencyScorer(sampler=lambda _: "", n_samples=0)

    def test_construction_rejects_negative_n_samples(self) -> None:
        with pytest.raises(ValueError, match="n_samples must be >= 1"):
            LexicalConsistencyScorer(sampler=lambda _: "", n_samples=-3)

    def test_perfect_agreement_yields_full_confidence(
        self, banking_prompt: str, banking_answer: str
    ) -> None:
        # All samples identical to the agent's answer -> Jaccard=1
        sampler = _make_sampler([banking_answer] * 3)
        scorer = LexicalConsistencyScorer(sampler=sampler, n_samples=3)
        result = scorer.score(banking_prompt, banking_answer)

        assert result.confidence == 1.0
        assert result.answer == banking_answer  # contract: do not substitute
        assert result.raw_scores["lexical_jaccard_mean"] == 1.0
        assert result.raw_scores["n_samples_succeeded"] == 3.0
        assert result.raw_scores["n_samples_failed"] == 0.0
        assert result.should_refuse is False
        assert result.samples == [banking_answer] * 3

    def test_zero_overlap_yields_zero_confidence(self) -> None:
        sampler = _make_sampler(["xyz pdq"] * 3)
        scorer = LexicalConsistencyScorer(sampler=sampler, n_samples=3)
        result = scorer.score("prompt", "alpha beta gamma")

        assert result.confidence == 0.0
        assert result.should_refuse is False  # all samples succeeded

    def test_partial_overlap_averages_correctly(self) -> None:
        # answer = {a, b}; samples = [{a, b}, {a, c}] -> jaccards [1.0, 1/3]
        sampler = _make_sampler(["a b", "a c"])
        scorer = LexicalConsistencyScorer(sampler=sampler, n_samples=2)
        result = scorer.score("prompt", "a b")
        assert result.confidence == pytest.approx((1.0 + 1 / 3) / 2)

    def test_sampler_errors_are_counted_and_logged(
        self, banking_prompt: str, banking_answer: str
    ) -> None:
        sampler = _flaky_sampler(
            [banking_answer, RuntimeError("backend timeout"), banking_answer]
        )
        scorer = LexicalConsistencyScorer(sampler=sampler, n_samples=3)
        result = scorer.score(banking_prompt, banking_answer)

        assert result.raw_scores["n_samples_succeeded"] == 2.0
        assert result.raw_scores["n_samples_failed"] == 1.0
        assert result.confidence == 1.0  # both successful samples agree fully
        assert result.should_refuse is False

    def test_all_samples_failing_triggers_refuse(self, banking_answer: str) -> None:
        sampler = _flaky_sampler(
            [RuntimeError("a"), RuntimeError("b"), RuntimeError("c")]
        )
        scorer = LexicalConsistencyScorer(sampler=sampler, n_samples=3)
        result = scorer.score("prompt", banking_answer)

        assert result.confidence == 0.0
        assert result.should_refuse is True  # nothing usable -> refuse
        assert result.raw_scores["n_samples_failed"] == 3.0
        assert result.samples is None

    def test_empty_answer_with_empty_samples_is_perfect_match(self) -> None:
        # Edge case: agent returned an empty string and samples agree
        sampler = _make_sampler(["", "", ""])
        scorer = LexicalConsistencyScorer(sampler=sampler, n_samples=3)
        result = scorer.score("prompt", "")
        # Two empty token sets -> jaccard returns 1.0 by convention
        assert result.confidence == 1.0
        assert result.answer == ""

    def test_diagnostics_records_requested_count(
        self, banking_prompt: str, banking_answer: str
    ) -> None:
        sampler = _make_sampler([banking_answer] * 5)
        scorer = LexicalConsistencyScorer(sampler=sampler, n_samples=5)
        result = scorer.score(banking_prompt, banking_answer)
        assert result.diagnostics == {"n_samples_requested": 5}

    def test_sampler_called_with_prompt(self, banking_prompt: str) -> None:
        seen: list[str] = []

        def _capture(p: str) -> str:
            seen.append(p)
            return "x"

        scorer = LexicalConsistencyScorer(sampler=_capture, n_samples=2)
        scorer.score(banking_prompt, "x")
        assert seen == [banking_prompt, banking_prompt]


# ---------------------------------------------------------------------------
# PTrueScorer
# ---------------------------------------------------------------------------


class TestPTrueScorer:
    def test_yes_reply_yields_full_confidence(
        self, banking_prompt: str, banking_answer: str
    ) -> None:
        scorer = PTrueScorer(verifier=lambda _: "yes")
        result = scorer.score(banking_prompt, banking_answer)
        assert result.confidence == 1.0
        assert result.answer == banking_answer
        assert result.raw_scores["p_true_probability"] == 1.0
        assert result.diagnostics["verifier_reply"] == "yes"
        assert result.should_refuse is False

    def test_no_reply_yields_zero_confidence(
        self, banking_prompt: str, banking_answer: str
    ) -> None:
        scorer = PTrueScorer(verifier=lambda _: "no")
        result = scorer.score(banking_prompt, banking_answer)
        assert result.confidence == 0.0

    def test_ambiguous_reply_yields_half(self) -> None:
        scorer = PTrueScorer(verifier=lambda _: "talvez")
        result = scorer.score("p", "a")
        assert result.confidence == 0.5

    def test_verifier_receives_formatted_prompt(
        self, banking_prompt: str, banking_answer: str
    ) -> None:
        captured: list[str] = []

        def _verifier(p: str) -> str:
            captured.append(p)
            return "yes"

        scorer = PTrueScorer(verifier=_verifier)
        scorer.score(banking_prompt, banking_answer)
        assert len(captured) == 1
        assert banking_prompt in captured[0]
        assert banking_answer in captured[0]
        # Default template includes the Bradesco quality-reviewer framing
        assert "Bradesco" in captured[0]

    def test_custom_template_substitution(self) -> None:
        captured: list[str] = []

        def _verifier(p: str) -> str:
            captured.append(p)
            return "yes"

        scorer = PTrueScorer(
            verifier=_verifier,
            template="Q: {prompt}\nA: {answer}\nCorrect?",
        )
        scorer.score("test prompt", "test answer")
        assert captured == ["Q: test prompt\nA: test answer\nCorrect?"]

    def test_verifier_exception_returns_zero_and_refuses(
        self, banking_prompt: str, banking_answer: str
    ) -> None:
        def _verifier(_: str) -> str:
            raise TimeoutError("verifier backend timed out")

        scorer = PTrueScorer(verifier=_verifier)
        result = scorer.score(banking_prompt, banking_answer)

        assert result.confidence == 0.0
        assert result.should_refuse is True
        assert result.answer == banking_answer
        assert result.raw_scores["p_true_error"] == 1.0
        assert result.diagnostics["error_type"] == "TimeoutError"
        assert "timed out" in result.diagnostics["error"]

    def test_default_template_constant_is_intact(self) -> None:
        # Sanity check: template still has both placeholders
        assert "{prompt}" in DEFAULT_VERIFIER_TEMPLATE
        assert "{answer}" in DEFAULT_VERIFIER_TEMPLATE


# ---------------------------------------------------------------------------
# CompositeAnswerScorer
# ---------------------------------------------------------------------------


class TestCompositeAnswerScorer:
    def test_construction_rejects_empty_scorer_list(self) -> None:
        with pytest.raises(ValueError, match="at least one scorer"):
            CompositeAnswerScorer(weighted_scorers=())

    def test_construction_rejects_zero_weight(self) -> None:
        with pytest.raises(ValueError, match="weights must be positive"):
            CompositeAnswerScorer(weighted_scorers=((_FixedScorer(0.5), 0.0),))

    def test_construction_rejects_negative_weight(self) -> None:
        with pytest.raises(ValueError, match="weights must be positive"):
            CompositeAnswerScorer(weighted_scorers=((_FixedScorer(0.5), -1.0),))

    def test_geometric_mean_with_equal_weights(self) -> None:
        # confidences 0.4, 0.9 with equal weights -> sqrt(0.4*0.9)
        sub_a = _FixedScorer(0.4)
        sub_b = _FixedScorer(0.9)
        composite = CompositeAnswerScorer(weighted_scorers=((sub_a, 1.0), (sub_b, 1.0)))
        result = composite.score("p", "a")
        assert result.confidence == pytest.approx(math.sqrt(0.4 * 0.9))

    def test_geometric_mean_with_unequal_weights(self) -> None:
        # exp(0.25*ln(0.5) + 0.75*ln(0.9)) — expected geometric mean
        sub_a = _FixedScorer(0.5)
        sub_b = _FixedScorer(0.9)
        composite = CompositeAnswerScorer(weighted_scorers=((sub_a, 1.0), (sub_b, 3.0)))
        result = composite.score("p", "a")
        expected = math.exp(0.25 * math.log(0.5) + 0.75 * math.log(0.9))
        assert result.confidence == pytest.approx(expected)

    def test_zero_subscore_drives_composite_to_floor(self) -> None:
        # Geometric mean property — any zero pulls the product to ~0,
        # which is the gate-friendly behaviour expected by regulators.
        composite = CompositeAnswerScorer(
            weighted_scorers=((_FixedScorer(0.0), 1.0), (_FixedScorer(0.95), 1.0))
        )
        result = composite.score("p", "a")
        # Floor is 1e-9 internally, so composite is sqrt(1e-9 * 0.95) ≈ 3e-5
        assert result.confidence < 1e-3

    def test_any_refuse_propagates(self) -> None:
        composite = CompositeAnswerScorer(
            weighted_scorers=(
                (_FixedScorer(0.9), 1.0),
                (_FixedScorer(0.9, should_refuse=True), 1.0),
            )
        )
        result = composite.score("p", "a")
        assert result.should_refuse is True

    def test_no_refuse_when_all_clear(self) -> None:
        composite = CompositeAnswerScorer(
            weighted_scorers=((_FixedScorer(0.9), 1.0), (_FixedScorer(0.5), 1.0))
        )
        result = composite.score("p", "a")
        assert result.should_refuse is False

    def test_diagnostics_records_each_component(self) -> None:
        sub_a = _FixedScorer(0.4)
        sub_b = _FixedScorer(0.6, should_refuse=True)
        composite = CompositeAnswerScorer(weighted_scorers=((sub_a, 1.0), (sub_b, 3.0)))
        result = composite.score("p", "a")

        comps = result.diagnostics["components"]
        assert len(comps) == 2
        assert comps[0]["scorer_index"] == 0
        assert comps[0]["scorer_type"] == "_FixedScorer"
        assert comps[0]["weight"] == pytest.approx(0.25)
        assert comps[0]["confidence"] == pytest.approx(0.4)
        assert comps[0]["should_refuse"] is False
        assert comps[1]["weight"] == pytest.approx(0.75)
        assert comps[1]["should_refuse"] is True

    def test_raw_scores_namespace_per_subscorer(self) -> None:
        sub_a = _FixedScorer(0.5, raw_scores={"foo": 0.1})
        sub_b = _FixedScorer(0.5, raw_scores={"bar": 0.2})
        composite = CompositeAnswerScorer(weighted_scorers=((sub_a, 1.0), (sub_b, 1.0)))
        result = composite.score("p", "a")

        assert result.raw_scores["_fixedscorer.foo"] == pytest.approx(0.1)
        assert result.raw_scores["_fixedscorer.bar"] == pytest.approx(0.2)
        assert result.raw_scores["composite_geometric"] == pytest.approx(0.5)

    def test_each_subscorer_called_with_same_prompt_and_answer(self) -> None:
        sub_a = _FixedScorer(0.9)
        sub_b = _FixedScorer(0.9)
        composite = CompositeAnswerScorer(weighted_scorers=((sub_a, 1.0), (sub_b, 1.0)))
        composite.score("the prompt", "the answer")
        assert sub_a.calls == [("the prompt", "the answer")]
        assert sub_b.calls == [("the prompt", "the answer")]

    def test_answer_field_preserved(self) -> None:
        composite = CompositeAnswerScorer(
            weighted_scorers=((_FixedScorer(0.5), 1.0),)
        )
        result = composite.score("p", "the original answer")
        assert result.answer == "the original answer"

    def test_composite_clamped_to_unit_interval(self) -> None:
        # If a subscorer returned exactly 1.0 across the board, composite
        # must remain in [0, 1] even with floating-point drift.
        composite = CompositeAnswerScorer(
            weighted_scorers=((_FixedScorer(1.0), 1.0), (_FixedScorer(1.0), 1.0))
        )
        result = composite.score("p", "a")
        assert 0.0 <= result.confidence <= 1.0
        assert result.confidence == pytest.approx(1.0)

    def test_protocol_compliance(self) -> None:
        # CompositeAnswerScorer must satisfy the AnswerScorer protocol so it
        # can itself be a sub-scorer of another composite.
        inner = CompositeAnswerScorer(weighted_scorers=((_FixedScorer(0.5), 1.0),))
        assert isinstance(inner, AnswerScorer)


# ---------------------------------------------------------------------------
# gate_answer_score
# ---------------------------------------------------------------------------


class TestGateAnswerScore:
    @pytest.mark.parametrize("threshold", [-0.01, 1.01, 2.0, -1.0])
    def test_threshold_out_of_range_raises(self, threshold: float) -> None:
        result = UncertaintyResult(answer="x", confidence=0.5)
        with pytest.raises(ValueError, match=r"threshold must be in"):
            gate_answer_score(result, threshold=threshold)

    def test_threshold_boundaries_allowed(self) -> None:
        result = UncertaintyResult(answer="x", confidence=0.5)
        # both endpoints inclusive
        gate_answer_score(result, threshold=0.0)
        gate_answer_score(result, threshold=1.0)

    def test_high_confidence_passes_through(self, banking_answer: str) -> None:
        result = UncertaintyResult(
            answer=banking_answer,
            confidence=0.92,
            raw_scores={"composite_geometric": 0.92},
        )
        gated = gate_answer_score(result, threshold=0.7)

        assert isinstance(gated, GuardResult)
        assert gated.outcome.decision == PolicyDecision.PASSTHROUGH
        assert gated.outcome.passed is True
        assert gated.output == banking_answer
        assert gated.rmf_subcategory == rmf_subcategory(PolicyDecision.PASSTHROUGH)
        assert gated.outcome.reason == "answer-attributed confidence met threshold"

    def test_low_confidence_abstains_with_marker(self, banking_answer: str) -> None:
        result = UncertaintyResult(answer=banking_answer, confidence=0.3)
        gated = gate_answer_score(result, threshold=0.7)

        assert gated.outcome.decision == PolicyDecision.ABSTAIN
        assert gated.outcome.passed is False
        assert gated.output == DEFAULT_ABSTAIN_MARKER
        assert gated.rmf_subcategory == rmf_subcategory(PolicyDecision.ABSTAIN)
        assert "below threshold" in gated.outcome.reason

    def test_at_threshold_passes(self, banking_answer: str) -> None:
        # Inclusive >= boundary: a score equal to threshold must release.
        result = UncertaintyResult(answer=banking_answer, confidence=0.7)
        gated = gate_answer_score(result, threshold=0.7)
        assert gated.outcome.decision == PolicyDecision.PASSTHROUGH

    def test_should_refuse_overrides_high_confidence(
        self, banking_answer: str
    ) -> None:
        # Even with confidence above threshold, a refuse flag forces ABSTAIN.
        # This matters when a sub-scorer detected an unrecoverable error.
        result = UncertaintyResult(
            answer=banking_answer, confidence=0.95, should_refuse=True
        )
        gated = gate_answer_score(result, threshold=0.5)
        assert gated.outcome.decision == PolicyDecision.ABSTAIN
        assert gated.output == DEFAULT_ABSTAIN_MARKER

    def test_custom_abstain_marker(self, banking_answer: str) -> None:
        result = UncertaintyResult(answer=banking_answer, confidence=0.1)
        gated = gate_answer_score(
            result, threshold=0.5, abstain_marker="[REVIEW NEEDED]"
        )
        assert gated.output == "[REVIEW NEEDED]"

    def test_metadata_propagates_raw_scores_and_scorer_tag(
        self, banking_answer: str
    ) -> None:
        # The audit trail and BCB 4893 reporter both read outcome.metadata
        # to know which scoring components fed the decision.
        result = UncertaintyResult(
            answer=banking_answer,
            confidence=0.8,
            raw_scores={
                "lexical_jaccard_mean": 0.85,
                "p_true_probability": 0.75,
                "composite_geometric": 0.8,
            },
        )
        gated = gate_answer_score(result, threshold=0.5)
        meta = gated.outcome.metadata
        assert meta["lexical_jaccard_mean"] == pytest.approx(0.85)
        assert meta["p_true_probability"] == pytest.approx(0.75)
        assert meta["composite_geometric"] == pytest.approx(0.8)
        # Distinct scorer tag so audit can attribute this to the post-hoc gate
        # rather than the upstream UncertaintyGuard
        assert meta["scorer"] == "lub.bridge.answer_scorer"

    def test_raw_uncertainty_result_preserved_in_envelope(
        self, banking_answer: str
    ) -> None:
        result = UncertaintyResult(answer=banking_answer, confidence=0.9)
        gated = gate_answer_score(result, threshold=0.5)
        assert gated.raw is result  # untouched, by reference

    def test_threshold_recorded_in_outcome(self, banking_answer: str) -> None:
        result = UncertaintyResult(answer=banking_answer, confidence=0.8)
        gated = gate_answer_score(result, threshold=0.42)
        assert gated.outcome.threshold == pytest.approx(0.42)
        assert gated.outcome.confidence == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# End-to-end: composite -> gate (mirrors the Bridge wire-up)
# ---------------------------------------------------------------------------


class TestEndToEndPipeline:
    """Mirror how Bridge wires the rescorer into the 9-stage pipeline.

    Stage 7 of the pipeline calls the agent, then post-hoc rescoring
    feeds gate_answer_score, which feeds the audit trail. These tests
    exercise the assembled chain with mocked LLM calls.
    """

    def test_high_agreement_passes_through_pipeline(
        self, banking_prompt: str, banking_answer: str
    ) -> None:
        sampler = _make_sampler([banking_answer] * 5)
        scorers: tuple[tuple[AnswerScorer, float], ...] = (
            (LexicalConsistencyScorer(sampler=sampler, n_samples=5), 1.0),
            (PTrueScorer(verifier=lambda _: "yes"), 2.0),
        )
        composite = CompositeAnswerScorer(weighted_scorers=scorers)
        score = composite.score(banking_prompt, banking_answer)
        gated = gate_answer_score(score, threshold=0.7)

        assert gated.outcome.decision == PolicyDecision.PASSTHROUGH
        assert gated.output == banking_answer

    def test_disagreement_escalates_via_abstain(
        self, banking_prompt: str, banking_answer: str
    ) -> None:
        # Lexical samples diverge, verifier says "no" -> low composite -> ABSTAIN
        sampler = _make_sampler(["totally unrelated"] * 5)
        scorers: tuple[tuple[AnswerScorer, float], ...] = (
            (LexicalConsistencyScorer(sampler=sampler, n_samples=5), 1.0),
            (PTrueScorer(verifier=lambda _: "no, the rate is wrong"), 2.0),
        )
        composite = CompositeAnswerScorer(weighted_scorers=scorers)
        score = composite.score(banking_prompt, banking_answer)
        gated = gate_answer_score(score, threshold=0.5)

        assert gated.outcome.decision == PolicyDecision.ABSTAIN
        assert gated.output == DEFAULT_ABSTAIN_MARKER
        # Audit-trail visibility: caller can see which signals failed
        meta = gated.outcome.metadata
        assert "ptruescorer.p_true_probability" in meta
        assert "lexicalconsistencyscorer.lexical_jaccard_mean" in meta

    def test_verifier_timeout_triggers_abstain_via_refuse(
        self, banking_prompt: str, banking_answer: str
    ) -> None:
        # Even with perfect lexical agreement, a verifier outage must not
        # silently release the answer — it must propagate as ABSTAIN.
        sampler = _make_sampler([banking_answer] * 3)

        def _broken_verifier(_: str) -> str:
            raise TimeoutError("Azure OpenAI 504")

        scorers: tuple[tuple[AnswerScorer, float], ...] = (
            (LexicalConsistencyScorer(sampler=sampler, n_samples=3), 1.0),
            (PTrueScorer(verifier=_broken_verifier), 1.0),
        )
        composite = CompositeAnswerScorer(weighted_scorers=scorers)
        score = composite.score(banking_prompt, banking_answer)
        gated = gate_answer_score(score, threshold=0.3)

        assert gated.outcome.decision == PolicyDecision.ABSTAIN
        assert score.should_refuse is True

    def test_pii_in_answer_passes_unmodified_when_confidence_ok(self) -> None:
        # The scorer is content-agnostic — PII redaction is a separate
        # responsibility (governance / audit). This test pins that
        # contract: no silent transformation of the agent's text.
        pii_answer = "Cliente CPF 123.456.789-00 deve transferir para conta 12345-6"
        sampler = _make_sampler([pii_answer] * 3)
        scorer = LexicalConsistencyScorer(sampler=sampler, n_samples=3)
        score = scorer.score("p", pii_answer)
        gated = gate_answer_score(score, threshold=0.5)
        assert gated.output == pii_answer  # unchanged

    def test_empty_input_handled_without_crashing(self) -> None:
        # Empty prompt + empty answer + empty samples -> jaccard = 1.0
        # The gate must still produce a valid envelope.
        sampler = _make_sampler([""] * 2)
        scorer = LexicalConsistencyScorer(sampler=sampler, n_samples=2)
        score = scorer.score("", "")
        gated = gate_answer_score(score, threshold=0.5)
        assert gated.outcome.decision == PolicyDecision.PASSTHROUGH
        assert gated.output == ""
