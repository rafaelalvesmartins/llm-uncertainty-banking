# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for ``lub.connectors.bridge.complexity``."""

from __future__ import annotations

import pytest

from lub.connectors.bridge.complexity import (
    ComplexityRouter,
    ComplexityScore,
    ComplexityTier,
)

# ---------------------------------------------------------------------------
# ComplexityRouter construction
# ---------------------------------------------------------------------------


class TestRouterConstruction:
    def test_default_thresholds_are_valid(self) -> None:
        router = ComplexityRouter()
        assert router.simple_threshold < router.medium_threshold

    def test_invalid_thresholds_raise(self) -> None:
        with pytest.raises(ValueError, match="simple_threshold"):
            ComplexityRouter(simple_threshold=5.0, medium_threshold=3.0)

    def test_equal_thresholds_raise(self) -> None:
        with pytest.raises(ValueError):
            ComplexityRouter(simple_threshold=2.0, medium_threshold=2.0)


# ---------------------------------------------------------------------------
# Signal extraction
# ---------------------------------------------------------------------------


class TestSignalExtraction:
    def setup_method(self) -> None:
        self.router = ComplexityRouter()

    def test_short_query(self) -> None:
        s = self.router.extract_signals("saldo")
        assert s.word_count == 1
        assert s.question_count == 0
        assert not s.has_multi_step
        assert not s.has_regulatory_jargon

    def test_question_marks_counted(self) -> None:
        s = self.router.extract_signals("Qual saldo? Posso transferir?")
        assert s.question_count == 2

    def test_multi_step_marker_detected(self) -> None:
        s = self.router.extract_signals(
            "Primeiro veja meu saldo, depois transfira 100 para Maria"
        )
        assert s.has_multi_step

    def test_regulatory_jargon_detected(self) -> None:
        s = self.router.extract_signals("Qual a posicao BCB sobre tributacao do PIX?")
        assert s.has_regulatory_jargon

    def test_conditional_detected(self) -> None:
        s = self.router.extract_signals("Se eu transferir 50000, paga IOF?")
        assert s.has_conditional

    def test_comparison_detected(self) -> None:
        s = self.router.extract_signals("Qual diferenca entre TED e DOC?")
        assert s.has_comparison

    def test_digit_density(self) -> None:
        s = self.router.extract_signals("Pagar 12345 reais")
        assert 0 < s.digit_density < 1

    def test_empty_query(self) -> None:
        s = self.router.extract_signals("")
        assert s.word_count == 0
        assert s.char_count == 0
        assert s.digit_density == 0


# ---------------------------------------------------------------------------
# Scoring + tier mapping
# ---------------------------------------------------------------------------


class TestTierMapping:
    def setup_method(self) -> None:
        self.router = ComplexityRouter()

    def test_simple_query_routes_to_simple(self) -> None:
        result = self.router.score("saldo")
        assert result.tier == ComplexityTier.SIMPLE

    def test_short_balance_query_simple(self) -> None:
        result = self.router.score("Qual meu saldo?")
        assert result.tier == ComplexityTier.SIMPLE

    def test_medium_query_routes_to_medium(self) -> None:
        # Multi-sentence, multi-question, but no regulatory.
        result = self.router.score(
            "Qual meu saldo? Quero transferir 500 reais para Joao via PIX agora."
        )
        assert result.tier in (ComplexityTier.MEDIUM, ComplexityTier.COMPLEX)

    def test_regulatory_query_complex(self) -> None:
        result = self.router.score(
            "Qual a posicao do BACEN sobre tributacao de PIX para PJ?"
        )
        assert result.tier == ComplexityTier.COMPLEX
        assert "regulatory" in result.rationale

    def test_conditional_pushes_complexity_up(self) -> None:
        simple = self.router.score("Posso transferir 1000?")
        conditional = self.router.score(
            "Se eu transferir 1000 hoje, qual o limite que sobra amanha caso eu queira fazer outra?"
        )
        assert conditional.raw_score > simple.raw_score

    def test_long_query_pushes_score_up(self) -> None:
        long_query = " ".join(["palavra"] * 40)
        result = self.router.score(long_query)
        assert result.raw_score >= 2.0

    def test_multi_step_pushes_to_at_least_medium(self) -> None:
        result = self.router.score(
            "Primeiro me mostre o saldo, depois transfira 100 para Maria"
        )
        assert result.tier in (ComplexityTier.MEDIUM, ComplexityTier.COMPLEX)


# ---------------------------------------------------------------------------
# ComplexityScore output
# ---------------------------------------------------------------------------


class TestScoreOutput:
    def test_score_includes_signals(self) -> None:
        router = ComplexityRouter()
        result = router.score("Qual meu saldo?")
        assert isinstance(result, ComplexityScore)
        assert result.signals.question_count == 1

    def test_rationale_is_human_readable(self) -> None:
        router = ComplexityRouter()
        result = router.score(
            "Primeiro qual a posicao do BCB sobre PIX, depois compare com TED?"
        )
        # Rationale should mention raw score and the strong markers.
        assert "raw=" in result.rationale
        # At least one of the contributing markers should appear
        assert any(
            marker in result.rationale
            for marker in ("regulatory", "comparison", "multi-step")
        )

    def test_score_is_deterministic(self) -> None:
        router = ComplexityRouter()
        a = router.score("Qual meu saldo da conta corrente?")
        b = router.score("Qual meu saldo da conta corrente?")
        assert a.tier == b.tier
        assert a.raw_score == b.raw_score


# ---------------------------------------------------------------------------
# Threshold tuning
# ---------------------------------------------------------------------------


class TestThresholdTuning:
    def test_raising_thresholds_demotes_queries(self) -> None:
        # Same query, two different routers.
        query = "Qual a posicao do BCB sobre tributacao?"

        strict = ComplexityRouter(simple_threshold=0.5, medium_threshold=1.5)
        lenient = ComplexityRouter(simple_threshold=5.0, medium_threshold=10.0)

        strict_tier = strict.score(query).tier
        lenient_tier = lenient.score(query).tier

        # Same content; strict router gives equal-or-higher tier.
        order = {
            ComplexityTier.SIMPLE: 0,
            ComplexityTier.MEDIUM: 1,
            ComplexityTier.COMPLEX: 2,
        }
        assert order[strict_tier] >= order[lenient_tier]
