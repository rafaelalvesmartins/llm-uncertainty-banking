# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for ``lub.connectors.bridge.grounding``.

Validates the bridge between Bridge's stage-4 RAG (``rag.RAGResult``)
and stage-7 guard (``guard.GuardResult``):

* :class:`GroundingScore` — geometric-mean confidence + audit dict.
* :class:`LexicalGroundingEvaluator` — citation / support / coverage.
* :func:`combine_with_guard` — gating downgrade (PASSTHROUGH -> FLAG /
  ABSTAIN) without substituting the agent's answer text.

LLM calls are not invoked here — grounding is a deterministic lexical
scorer. The "LLM answer" is a plain string fixture; the guard verdict
is built from a stub ``UncertaintyResult`` / ``PolicyOutcome``.
"""

from __future__ import annotations

import pytest

from lub.connectors.bridge.grounding import (
    GroundingEvaluator,
    GroundingScore,
    LexicalGroundingEvaluator,
    combine_with_guard,
)
from lub.connectors.bridge.rag import (
    Document,
    RAGResult,
    RetrievedDocument,
)
from lub.guard import GuardResult, PolicyDecision, PolicyOutcome, rmf_subcategory
from lub.types import UncertaintyResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _retrieved(
    doc_id: str,
    text: str,
    source: str,
    score: float,
) -> RetrievedDocument:
    return RetrievedDocument(
        document=Document(id=doc_id, text=text, source=source),
        score=score,
    )


@pytest.fixture
def rag_pix_ted() -> RAGResult:
    """Two-doc retrieval over PIX + TED, both well above min_top_score."""
    retrieved = (
        _retrieved(
            "pix-001",
            (
                "PIX e o sistema de pagamentos instantaneos do Banco Central "
                "Brasil funciona vinte quatro horas todos dias"
            ),
            "BCB Manual PIX",
            score=0.62,
        ),
        _retrieved(
            "ted-001",
            (
                "TED transferencia eletronica disponivel opera dias uteis "
                "ate dezessete horas valor minimo zero centavos"
            ),
            "Manual Bradesco TED",
            score=0.41,
        ),
    )
    return RAGResult(
        grounded_prompt="(prompt elided)",
        retrieved=retrieved,
        citations=("BCB Manual PIX", "Manual Bradesco TED"),
        duration_ms=2.5,
    )


@pytest.fixture
def rag_empty() -> RAGResult:
    """Retrieval that returned nothing — has_grounding is False."""
    return RAGResult(
        grounded_prompt="(prompt elided)",
        retrieved=(),
        citations=(),
        duration_ms=1.0,
    )


@pytest.fixture
def rag_weak_top_score() -> RAGResult:
    """Retrieval where the top doc cleared the pipeline gate but only barely."""
    retrieved = (
        _retrieved(
            "pix-001",
            "PIX pagamentos instantaneos Banco Central horas",
            "BCB Manual PIX",
            score=0.05,
        ),
    )
    return RAGResult(
        grounded_prompt="(prompt elided)",
        retrieved=retrieved,
        citations=("BCB Manual PIX",),
        duration_ms=1.2,
    )


def _make_guard_result(
    *,
    answer: str = "PIX funciona 24h.",
    confidence: float = 0.85,
    decision: PolicyDecision = PolicyDecision.PASSTHROUGH,
    threshold: float = 0.5,
    passed: bool = True,
    extra_meta: dict | None = None,
) -> GuardResult:
    raw = UncertaintyResult(
        answer=answer,
        confidence=confidence,
        raw_scores={"entropy": 0.21},
    )
    outcome = PolicyOutcome(
        decision=decision,
        confidence=confidence,
        threshold=threshold,
        passed=passed,
        answer=answer,
        reason="ok",
        metadata=dict(extra_meta or {}),
    )
    return GuardResult(
        raw=raw,
        outcome=outcome,
        output=answer,
        rmf_subcategory=rmf_subcategory(decision),
    )


# ---------------------------------------------------------------------------
# GroundingScore
# ---------------------------------------------------------------------------


class TestGroundingScore:
    def test_confidence_is_geometric_mean(self) -> None:
        score = GroundingScore(
            citation_score=0.8,
            support_score=0.5,
            coverage_score=0.25,
            cited_sources=("BCB Manual PIX",),
            missing_sources=(),
            unsupported_token_ratio=0.5,
        )
        expected = (0.8 * 0.5 * 0.25) ** (1.0 / 3.0)
        assert score.confidence == pytest.approx(expected, abs=1e-9)

    def test_zero_citation_collapses_confidence(self) -> None:
        score = GroundingScore(
            citation_score=0.0,
            support_score=1.0,
            coverage_score=1.0,
            cited_sources=(),
            missing_sources=("BCB Manual PIX",),
            unsupported_token_ratio=0.0,
        )
        assert score.confidence == 0.0

    def test_zero_support_collapses_confidence(self) -> None:
        score = GroundingScore(
            citation_score=1.0,
            support_score=0.0,
            coverage_score=1.0,
            cited_sources=("BCB Manual PIX",),
            missing_sources=(),
            unsupported_token_ratio=1.0,
        )
        assert score.confidence == 0.0

    def test_zero_coverage_collapses_confidence(self) -> None:
        score = GroundingScore(
            citation_score=1.0,
            support_score=1.0,
            coverage_score=0.0,
            cited_sources=("BCB Manual PIX",),
            missing_sources=(),
            unsupported_token_ratio=0.0,
        )
        assert score.confidence == 0.0

    def test_perfect_score_is_one(self) -> None:
        score = GroundingScore(
            citation_score=1.0,
            support_score=1.0,
            coverage_score=1.0,
            cited_sources=("BCB Manual PIX",),
            missing_sources=(),
            unsupported_token_ratio=0.0,
        )
        assert score.confidence == pytest.approx(1.0, abs=1e-9)

    def test_confidence_clamps_out_of_range_inputs(self) -> None:
        # Defensive: even if upstream produced something > 1 or < 0,
        # the property must still return a value in [0, 1].
        score = GroundingScore(
            citation_score=1.5,
            support_score=-0.2,
            coverage_score=2.0,
            cited_sources=(),
            missing_sources=(),
            unsupported_token_ratio=0.0,
        )
        # support_score clamped to 0 -> confidence is 0.
        assert score.confidence == 0.0

    def test_as_audit_is_json_serializable(self) -> None:
        import json

        score = GroundingScore(
            citation_score=0.5,
            support_score=0.6,
            coverage_score=0.7,
            cited_sources=("BCB Manual PIX",),
            missing_sources=("Manual Bradesco TED",),
            unsupported_token_ratio=0.4,
        )
        audit = score.as_audit()
        # All keys present.
        assert set(audit) == {
            "citation_score",
            "support_score",
            "coverage_score",
            "unsupported_token_ratio",
            "confidence",
            "cited_sources",
            "missing_sources",
        }
        # And round-trips through json.
        encoded = json.dumps(audit)
        decoded = json.loads(encoded)
        assert decoded["cited_sources"] == ["BCB Manual PIX"]
        assert decoded["missing_sources"] == ["Manual Bradesco TED"]
        assert decoded["confidence"] == pytest.approx(score.confidence)


# ---------------------------------------------------------------------------
# LexicalGroundingEvaluator — construction
# ---------------------------------------------------------------------------


class TestEvaluatorConstruction:
    def test_implements_protocol(self) -> None:
        evaluator = LexicalGroundingEvaluator()
        assert isinstance(evaluator, GroundingEvaluator)

    @pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0])
    def test_invalid_min_top_score_raises(self, bad: float) -> None:
        with pytest.raises(ValueError, match="min_top_score"):
            LexicalGroundingEvaluator(min_top_score=bad)

    @pytest.mark.parametrize("bad", [-0.1, 1.1])
    def test_invalid_partial_credit_raises(self, bad: float) -> None:
        with pytest.raises(ValueError, match="partial_citation_credit"):
            LexicalGroundingEvaluator(partial_citation_credit=bad)


# ---------------------------------------------------------------------------
# LexicalGroundingEvaluator — coverage signal
# ---------------------------------------------------------------------------


class TestCoverageScore:
    def test_empty_retrieval_is_zero(self, rag_empty: RAGResult) -> None:
        evaluator = LexicalGroundingEvaluator()
        score = evaluator.score("anything", rag_empty)
        assert score.coverage_score == 0.0

    def test_strong_top_score_is_one(self, rag_pix_ted: RAGResult) -> None:
        evaluator = LexicalGroundingEvaluator(min_top_score=0.10)
        # top score 0.62 >> 0.10
        score = evaluator.score("PIX funciona 24h. [Fonte: BCB Manual PIX]", rag_pix_ted)
        assert score.coverage_score == 1.0

    def test_weak_top_score_decays_linearly(self, rag_weak_top_score: RAGResult) -> None:
        evaluator = LexicalGroundingEvaluator(min_top_score=0.10)
        # top score 0.05, min_top_score 0.10 -> coverage 0.5
        score = evaluator.score(
            "PIX funciona vinte quatro horas. [Fonte: BCB Manual PIX]",
            rag_weak_top_score,
        )
        assert score.coverage_score == pytest.approx(0.5, abs=1e-9)


# ---------------------------------------------------------------------------
# LexicalGroundingEvaluator — citation signal
# ---------------------------------------------------------------------------


class TestCitationScore:
    def test_full_citation_set_is_one(self, rag_pix_ted: RAGResult) -> None:
        evaluator = LexicalGroundingEvaluator()
        answer = (
            "PIX funciona 24h e TED so dias uteis. "
            "[Fonte: BCB Manual PIX] [Fonte: Manual Bradesco TED]"
        )
        score = evaluator.score(answer, rag_pix_ted)
        assert score.citation_score == 1.0
        assert score.missing_sources == ()

    def test_no_citation_marker_is_zero(self, rag_pix_ted: RAGResult) -> None:
        evaluator = LexicalGroundingEvaluator()
        answer = "PIX funciona 24h horas todos dias."
        score = evaluator.score(answer, rag_pix_ted)
        assert score.citation_score == 0.0
        assert score.cited_sources == ()
        # Every retrieved source is marked as missing.
        assert set(score.missing_sources) == set(rag_pix_ted.citations)

    def test_fabricated_citation_is_zero(self, rag_pix_ted: RAGResult) -> None:
        # Worst case: model cites a source that was NEVER retrieved.
        # This is the "fabricated citation" failure mode — must zero out.
        evaluator = LexicalGroundingEvaluator()
        answer = "PIX e gratuito para PJ. [Fonte: Manual Inventado v9]"
        score = evaluator.score(answer, rag_pix_ted)
        assert score.citation_score == 0.0
        assert "Manual Inventado v9" in score.cited_sources

    def test_partial_citation_gets_partial_credit(self, rag_pix_ted: RAGResult) -> None:
        evaluator = LexicalGroundingEvaluator(partial_citation_credit=0.5)
        # Cites PIX but not TED -> 1 of 2 retrieved sources matched.
        answer = "PIX funciona 24h horas. [Fonte: BCB Manual PIX]"
        score = evaluator.score(answer, rag_pix_ted)
        # partial_citation_credit + (1 - partial_citation_credit) * 0.5 = 0.75
        assert score.citation_score == pytest.approx(0.75, abs=1e-9)
        assert "Manual Bradesco TED" in score.missing_sources
        assert "BCB Manual PIX" not in score.missing_sources

    def test_citation_marker_is_case_insensitive(self, rag_pix_ted: RAGResult) -> None:
        evaluator = LexicalGroundingEvaluator()
        # Lowercase 'fonte' must still be recognized.
        answer = (
            "PIX funciona 24h e TED so dias uteis. "
            "[fonte: bcb manual pix] [FONTE: Manual Bradesco TED]"
        )
        score = evaluator.score(answer, rag_pix_ted)
        assert score.citation_score == 1.0

    def test_partial_credit_zero_means_all_or_nothing(self, rag_pix_ted: RAGResult) -> None:
        evaluator = LexicalGroundingEvaluator(partial_citation_credit=0.0)
        answer = "PIX funciona 24h horas. [Fonte: BCB Manual PIX]"
        score = evaluator.score(answer, rag_pix_ted)
        # 1 of 2 sources matched, partial_credit=0 -> 0 + 1.0*0.5 = 0.5
        assert score.citation_score == pytest.approx(0.5, abs=1e-9)


# ---------------------------------------------------------------------------
# LexicalGroundingEvaluator — support signal
# ---------------------------------------------------------------------------


class TestSupportScore:
    def test_empty_answer_is_zero(self, rag_pix_ted: RAGResult) -> None:
        evaluator = LexicalGroundingEvaluator()
        score = evaluator.score("", rag_pix_ted)
        assert score.support_score == 0.0
        assert score.unsupported_token_ratio == 0.0

    def test_answer_tokens_mostly_in_evidence(self, rag_pix_ted: RAGResult) -> None:
        evaluator = LexicalGroundingEvaluator()
        # Most content tokens appear in the retrieved evidence union.
        # The citation marker leaks its own tokens (fonte / bcb / manual)
        # which are absent from doc.text, so support is < 1.0 — that's
        # by design: a faithful answer with a citation will not score a
        # perfect 1.0 under the lexical evaluator. Production strict
        # evaluators (NLI) can; the lexical one is a cheap pre-filter.
        answer = (
            "PIX pagamentos instantaneos Banco Central Brasil "
            "funciona vinte quatro horas todos dias. "
            "[Fonte: BCB Manual PIX]"
        )
        score = evaluator.score(answer, rag_pix_ted)
        assert score.support_score > 0.7
        assert score.unsupported_token_ratio < 0.3

    def test_answer_with_no_evidence_overlap_is_zero(self, rag_pix_ted: RAGResult) -> None:
        evaluator = LexicalGroundingEvaluator()
        # No citation marker, no overlap with retrieved evidence.
        answer = "futebol pizza cinema televisao musica viagem turismo praia"
        score = evaluator.score(answer, rag_pix_ted)
        assert score.support_score == 0.0
        assert score.unsupported_token_ratio == 1.0

    def test_no_grounding_forces_support_zero(self, rag_empty: RAGResult) -> None:
        evaluator = LexicalGroundingEvaluator()
        score = evaluator.score("PIX funciona 24h horas", rag_empty)
        assert score.support_score == 0.0
        assert score.unsupported_token_ratio == 1.0

    def test_unsupported_ratio_is_complement(self, rag_pix_ted: RAGResult) -> None:
        evaluator = LexicalGroundingEvaluator()
        answer = (
            "PIX pagamentos instantaneos futebol pizza "
            "[Fonte: BCB Manual PIX]"
        )
        score = evaluator.score(answer, rag_pix_ted)
        assert score.support_score + score.unsupported_token_ratio == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# LexicalGroundingEvaluator — integrated score()
# ---------------------------------------------------------------------------


class TestEvaluatorScore:
    def test_well_grounded_answer_high_confidence(self, rag_pix_ted: RAGResult) -> None:
        evaluator = LexicalGroundingEvaluator()
        answer = (
            "PIX e o sistema de pagamentos instantaneos do Banco Central "
            "Brasil funciona vinte quatro horas. "
            "[Fonte: BCB Manual PIX] [Fonte: Manual Bradesco TED]"
        )
        score = evaluator.score(answer, rag_pix_ted)
        assert score.confidence > 0.8

    def test_hallucinated_answer_low_confidence(self, rag_pix_ted: RAGResult) -> None:
        # Confident-sounding but ungrounded + fabricated source.
        evaluator = LexicalGroundingEvaluator()
        answer = (
            "PIX e gratuito para PJ ate cinquenta mil reais por mes. "
            "[Fonte: Manual Inventado v9]"
        )
        score = evaluator.score(answer, rag_pix_ted)
        # Fabricated source -> citation_score == 0 -> confidence == 0.
        assert score.confidence == 0.0

    def test_log_called(
        self,
        rag_pix_ted: RAGResult,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # structlog defaults route through stdlib logging in tests.
        evaluator = LexicalGroundingEvaluator()
        with caplog.at_level("INFO"):
            evaluator.score(
                "PIX funciona 24h. [Fonte: BCB Manual PIX]",
                rag_pix_ted,
            )
        # At minimum, scoring should not raise; we don't depend on the
        # exact logger backend being captured here.


# ---------------------------------------------------------------------------
# combine_with_guard — parameter validation
# ---------------------------------------------------------------------------


class TestCombineWithGuardValidation:
    def test_hard_floor_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="hard_floor"):
            combine_with_guard(
                _make_guard_result(),
                GroundingScore(0.5, 0.5, 0.5, (), (), 0.5),
                hard_floor=1.5,
                soft_floor=0.5,
            )

    def test_soft_floor_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="soft_floor"):
            combine_with_guard(
                _make_guard_result(),
                GroundingScore(0.5, 0.5, 0.5, (), (), 0.5),
                hard_floor=0.1,
                soft_floor=-0.1,
            )

    def test_hard_floor_above_soft_floor_raises(self) -> None:
        with pytest.raises(ValueError, match="hard_floor.*soft_floor"):
            combine_with_guard(
                _make_guard_result(),
                GroundingScore(0.5, 0.5, 0.5, (), (), 0.5),
                hard_floor=0.8,
                soft_floor=0.2,
            )


# ---------------------------------------------------------------------------
# combine_with_guard — gating semantics
# ---------------------------------------------------------------------------


def _grounding_with_confidence(target: float) -> GroundingScore:
    """Build a GroundingScore whose geometric-mean confidence equals target.

    Setting all three components equal to ``target`` makes the geometric
    mean ``(target * target * target) ** (1/3) == target``.
    """
    return GroundingScore(
        citation_score=target,
        support_score=target,
        coverage_score=target,
        cited_sources=("BCB Manual PIX",) if target > 0 else (),
        missing_sources=(),
        unsupported_token_ratio=1.0 - target,
    )


class TestCombineWithGuardGating:
    def test_high_grounding_passes_through_unchanged(self) -> None:
        verdict = _make_guard_result(
            decision=PolicyDecision.PASSTHROUGH,
            confidence=0.92,
        )
        grounding = _grounding_with_confidence(0.85)  # above soft_floor=0.5
        result = combine_with_guard(verdict, grounding)
        assert result is verdict

    def test_low_grounding_forces_abstain(self) -> None:
        verdict = _make_guard_result(
            decision=PolicyDecision.PASSTHROUGH,
            confidence=0.92,
            passed=True,
        )
        grounding = _grounding_with_confidence(0.05)  # below hard_floor=0.20
        result = combine_with_guard(verdict, grounding)
        assert result.outcome.decision is PolicyDecision.ABSTAIN
        assert result.outcome.passed is False
        # Underlying LLM-side confidence preserved — we never overwrite it.
        assert result.outcome.confidence == pytest.approx(verdict.outcome.confidence)
        assert "grounding" in result.outcome.reason

    def test_medium_grounding_forces_flag(self) -> None:
        verdict = _make_guard_result(
            decision=PolicyDecision.PASSTHROUGH,
            confidence=0.92,
            passed=True,
        )
        grounding = _grounding_with_confidence(0.35)  # between floors
        result = combine_with_guard(
            verdict,
            grounding,
            hard_floor=0.20,
            soft_floor=0.50,
        )
        assert result.outcome.decision is PolicyDecision.FLAG
        # FLAG ships the answer, so passed stays True from the guard.
        assert result.outcome.passed is True
        assert "FLAG" in result.outcome.reason

    def test_flag_preserves_answer_text(self) -> None:
        # Bridge contract: grounding GATES, does not SUBSTITUTE.
        verdict = _make_guard_result(answer="PIX funciona 24h.")
        grounding = _grounding_with_confidence(0.35)
        result = combine_with_guard(verdict, grounding)
        assert result.output == "PIX funciona 24h."

    def test_abstain_preserves_answer_when_no_marker(self) -> None:
        verdict = _make_guard_result(answer="PIX funciona 24h.")
        grounding = _grounding_with_confidence(0.05)
        result = combine_with_guard(verdict, grounding, abstain_marker=None)
        # Without an explicit abstain_marker, the original output stays —
        # the *decision* is what signals downstream that the answer is
        # suppressed for review.
        assert result.output == "PIX funciona 24h."

    def test_abstain_uses_explicit_marker(self) -> None:
        verdict = _make_guard_result(answer="PIX funciona 24h.")
        grounding = _grounding_with_confidence(0.05)
        result = combine_with_guard(
            verdict,
            grounding,
            abstain_marker="[Encaminhado para especialista — grounding insuficiente]",
        )
        assert result.output.startswith("[Encaminhado")

    def test_metadata_includes_grounding_audit(self) -> None:
        verdict = _make_guard_result(extra_meta={"pre_existing": "preserved"})
        grounding = _grounding_with_confidence(0.05)
        result = combine_with_guard(verdict, grounding)
        meta = result.outcome.metadata
        assert "grounding" in meta
        assert "grounding_downgrade" in meta
        assert "grounding_prior_decision" in meta
        # And we don't clobber pre-existing keys.
        assert meta["pre_existing"] == "preserved"

    def test_metadata_grounding_block_is_audit_dict(self) -> None:
        verdict = _make_guard_result()
        grounding = _grounding_with_confidence(0.05)
        result = combine_with_guard(verdict, grounding)
        block = result.outcome.metadata["grounding"]
        assert set(block) >= {
            "citation_score",
            "support_score",
            "coverage_score",
            "confidence",
            "cited_sources",
            "missing_sources",
        }

    def test_prior_decision_recorded(self) -> None:
        verdict = _make_guard_result(decision=PolicyDecision.PASSTHROUGH)
        grounding = _grounding_with_confidence(0.05)
        result = combine_with_guard(verdict, grounding)
        assert result.outcome.metadata["grounding_prior_decision"] == "passthrough"

    def test_already_failing_verdict_still_downgraded(self) -> None:
        # Guard said FLAG, grounding says ABSTAIN — keep the stricter one.
        verdict = _make_guard_result(
            decision=PolicyDecision.FLAG,
            passed=True,
        )
        grounding = _grounding_with_confidence(0.05)
        result = combine_with_guard(verdict, grounding)
        assert result.outcome.decision is PolicyDecision.ABSTAIN
        assert result.outcome.passed is False

    def test_grounding_at_soft_floor_passes_through(self) -> None:
        verdict = _make_guard_result()
        grounding = _grounding_with_confidence(0.50 + 1e-6)
        result = combine_with_guard(verdict, grounding, hard_floor=0.20, soft_floor=0.50)
        # ">= soft_floor" branch: returns verdict unchanged.
        assert result is verdict

    def test_grounding_at_hard_floor_is_flag_not_abstain(self) -> None:
        verdict = _make_guard_result()
        grounding = _grounding_with_confidence(0.20)  # exactly at hard_floor
        result = combine_with_guard(verdict, grounding, hard_floor=0.20, soft_floor=0.50)
        # "< hard_floor" is strict, so equal -> FLAG, not ABSTAIN.
        assert result.outcome.decision is PolicyDecision.FLAG


# ---------------------------------------------------------------------------
# End-to-end: full Bridge stage-4 -> stage-7 connection
# ---------------------------------------------------------------------------


class TestRagToGuardConnection:
    """Smoke tests for the actual bridge wiring: RAG output -> evaluator -> combiner."""

    def test_grounded_answer_survives_guard(self, rag_pix_ted: RAGResult) -> None:
        evaluator = LexicalGroundingEvaluator()
        verdict = _make_guard_result(
            answer=(
                "PIX e o sistema de pagamentos instantaneos do Banco Central, "
                "funciona vinte quatro horas todos dias. "
                "[Fonte: BCB Manual PIX] [Fonte: Manual Bradesco TED]"
            ),
            confidence=0.91,
            decision=PolicyDecision.PASSTHROUGH,
        )
        grounding = evaluator.score(verdict.output, rag_pix_ted)
        combined = combine_with_guard(verdict, grounding)
        assert combined.outcome.decision is PolicyDecision.PASSTHROUGH

    def test_hallucinated_answer_is_downgraded_to_abstain(
        self, rag_pix_ted: RAGResult
    ) -> None:
        evaluator = LexicalGroundingEvaluator()
        # A confident-but-fabricated answer is the exact failure mode the
        # grounding signal exists to prevent.
        verdict = _make_guard_result(
            answer=(
                "PIX e gratuito para PJ ate cinquenta mil reais. "
                "[Fonte: Manual Inventado v9]"
            ),
            confidence=0.93,
            decision=PolicyDecision.PASSTHROUGH,
        )
        grounding = evaluator.score(verdict.output, rag_pix_ted)
        combined = combine_with_guard(verdict, grounding)
        assert combined.outcome.decision is PolicyDecision.ABSTAIN

    def test_no_retrieval_forces_downgrade(self, rag_empty: RAGResult) -> None:
        # If RAG returned nothing, even a citation-shaped answer must
        # not pass — coverage is 0, so the geometric mean is 0.
        evaluator = LexicalGroundingEvaluator()
        verdict = _make_guard_result(
            answer="PIX funciona 24h. [Fonte: BCB Manual PIX]",
            confidence=0.95,
            decision=PolicyDecision.PASSTHROUGH,
        )
        grounding = evaluator.score(verdict.output, rag_empty)
        assert grounding.confidence == 0.0
        combined = combine_with_guard(verdict, grounding)
        assert combined.outcome.decision is PolicyDecision.ABSTAIN

    def test_empty_customer_answer_downgrades(self, rag_pix_ted: RAGResult) -> None:
        evaluator = LexicalGroundingEvaluator()
        verdict = _make_guard_result(answer="", confidence=0.7)
        grounding = evaluator.score(verdict.output, rag_pix_ted)
        # Empty answer -> support=0 -> confidence=0 -> ABSTAIN.
        assert grounding.confidence == 0.0
        combined = combine_with_guard(verdict, grounding)
        assert combined.outcome.decision is PolicyDecision.ABSTAIN

    def test_pii_or_amount_text_still_gated_by_grounding(
        self, rag_pix_ted: RAGResult
    ) -> None:
        # An answer that quotes a specific R$ amount NOT present in the
        # retrieved docs should fail the support gate. This is the
        # "invented number" failure — high LLM confidence, no evidence.
        evaluator = LexicalGroundingEvaluator()
        verdict = _make_guard_result(
            answer=(
                "Para cliente CPF 123 456 789 00 a tarifa PIX e dezessete reais "
                "quarenta centavos cobrados mensalmente faturamento "
                "[Fonte: BCB Manual PIX]"
            ),
            confidence=0.95,
        )
        grounding = evaluator.score(verdict.output, rag_pix_ted)
        # Most content tokens (cpf digits, tarifa, dezessete, quarenta,
        # cobrados, mensalmente, faturamento) are absent from the
        # retrieved evidence -> low support -> low combined confidence.
        # We assert directly on the support signal rather than the final
        # decision so the test isn't entangled with floor tuning.
        assert grounding.support_score < 0.5
        assert grounding.confidence < 0.7
