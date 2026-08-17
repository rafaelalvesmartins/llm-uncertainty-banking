# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""Tests for lub.cnh.heatmap renderers."""

from __future__ import annotations

import pytest

from lub.cnh.heatmap import render_heatmap_html, render_heatmap_markdown
from lub.cnh.score import ParagraphScore
from lub.cnh.thresholds import (
    CASUAL_PROFILE,
    LEGAL_PROFILE,
    MARKETING_PROFILE,
    TECHNICAL_PROFILE,
    DomainProfile,
)

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def green_score() -> ParagraphScore:
    # 0.95 >= LEGAL_PROFILE.green_min (0.90) -> green
    return ParagraphScore(text="High-confidence paragraph.", confidence=0.95)


@pytest.fixture
def yellow_score() -> ParagraphScore:
    # 0.75 in [0.70, 0.90) under LEGAL_PROFILE -> yellow
    return ParagraphScore(text="Borderline paragraph.", confidence=0.75)


@pytest.fixture
def red_score() -> ParagraphScore:
    # 0.40 < LEGAL_PROFILE.yellow_min (0.70) -> red
    return ParagraphScore(text="Low-confidence paragraph.", confidence=0.40)


@pytest.fixture
def trio(
    green_score: ParagraphScore,
    yellow_score: ParagraphScore,
    red_score: ParagraphScore,
) -> list[ParagraphScore]:
    return [green_score, yellow_score, red_score]


# ---------------------------------------------------------------------------
# render_heatmap_html -- structure
# ---------------------------------------------------------------------------


class TestRenderHeatmapHtmlStructure:
    def test_returns_self_contained_html_document(self, trio: list[ParagraphScore]) -> None:
        out = render_heatmap_html(trio)
        assert out.startswith("<!DOCTYPE html>")
        assert "<html" in out
        assert out.rstrip().endswith("</html>")
        assert "<style>" in out
        assert "<head>" in out
        assert "<body>" in out

    def test_no_external_resources(self, trio: list[ParagraphScore]) -> None:
        """Spec: CSS only, no JS, no external links."""
        out = render_heatmap_html(trio)
        assert "<script" not in out.lower()
        assert "http://" not in out
        assert "https://" not in out
        assert "<link" not in out.lower()

    def test_default_title_used(self, trio: list[ParagraphScore]) -> None:
        out = render_heatmap_html(trio)
        assert "Calibrated Narrative Heatmap" in out
        assert "<title>Calibrated Narrative Heatmap</title>" in out

    def test_custom_title_is_rendered_and_escaped(self) -> None:
        out = render_heatmap_html([], title="<script>evil</script>")
        # Escaped in both <title> and <h1>.
        assert "<script>evil</script>" not in out
        assert "&lt;script&gt;evil&lt;/script&gt;" in out

    def test_legend_contains_profile_name_and_thresholds(self, trio: list[ParagraphScore]) -> None:
        out = render_heatmap_html(trio, profile=LEGAL_PROFILE)
        assert "legal" in out
        assert "0.90" in out  # green_min
        assert "0.70" in out  # yellow_min

    def test_empty_scores_renders_placeholder_not_error(self) -> None:
        out = render_heatmap_html([])
        assert "<!DOCTYPE html>" in out
        assert "No paragraphs to render" in out


# ---------------------------------------------------------------------------
# render_heatmap_html -- classification & content
# ---------------------------------------------------------------------------


class TestRenderHeatmapHtmlContent:
    def test_each_paragraph_gets_correct_class(self, trio: list[ParagraphScore]) -> None:
        out = render_heatmap_html(trio, profile=LEGAL_PROFILE)
        # Three .para blocks, one per tier.
        assert out.count('class="para green"') == 1
        assert out.count('class="para yellow"') == 1
        assert out.count('class="para red"') == 1

    def test_confidence_is_displayed_two_decimals(self, trio: list[ParagraphScore]) -> None:
        out = render_heatmap_html(trio)
        assert "0.95" in out
        assert "0.75" in out
        assert "0.40" in out

    def test_paragraph_text_is_html_escaped(self) -> None:
        score = ParagraphScore(
            text='Bad <img src=x onerror="alert(1)">',
            confidence=0.95,
        )
        out = render_heatmap_html([score])
        # Raw tag must NOT appear; escaped form must.
        assert '<img src=x onerror="alert(1)">' not in out
        assert "&lt;img" in out
        assert "alert(1)" in out  # escaped, but the literal text is preserved

    def test_newlines_in_text_become_br(self) -> None:
        score = ParagraphScore(text="line one\nline two", confidence=0.95)
        out = render_heatmap_html([score])
        assert "line one<br>line two" in out

    def test_paragraph_order_preserved(self) -> None:
        scores = [
            ParagraphScore(text="alpha", confidence=0.95),
            ParagraphScore(text="bravo", confidence=0.75),
            ParagraphScore(text="charlie", confidence=0.40),
        ]
        out = render_heatmap_html(scores)
        assert out.index("alpha") < out.index("bravo") < out.index("charlie")


# ---------------------------------------------------------------------------
# render_heatmap_html -- profile sensitivity
# ---------------------------------------------------------------------------


class TestRenderHeatmapHtmlProfile:
    @pytest.mark.parametrize(
        ("profile", "expected_color"),
        [
            (LEGAL_PROFILE, "yellow"),  # 0.80 < 0.90 -> yellow
            (TECHNICAL_PROFILE, "green"),  # 0.80 >= 0.80 -> green
            (MARKETING_PROFILE, "green"),  # 0.80 >= 0.70 -> green
            (CASUAL_PROFILE, "green"),  # 0.80 >= 0.60 -> green
        ],
    )
    def test_same_score_reclassified_per_profile(
        self, profile: DomainProfile, expected_color: str
    ) -> None:
        score = ParagraphScore(text="text", confidence=0.80)
        out = render_heatmap_html([score], profile=profile)
        assert f'class="para {expected_color}"' in out

    def test_boundary_at_green_min_is_green(self) -> None:
        # exact boundary: classify uses >=, so green_min itself is green
        score = ParagraphScore(text="boundary", confidence=LEGAL_PROFILE.green_min)
        out = render_heatmap_html([score], profile=LEGAL_PROFILE)
        assert 'class="para green"' in out

    def test_boundary_at_yellow_min_is_yellow(self) -> None:
        score = ParagraphScore(text="boundary", confidence=LEGAL_PROFILE.yellow_min)
        out = render_heatmap_html([score], profile=LEGAL_PROFILE)
        assert 'class="para yellow"' in out

    def test_just_below_yellow_min_is_red(self) -> None:
        score = ParagraphScore(text="boundary", confidence=LEGAL_PROFILE.yellow_min - 0.01)
        out = render_heatmap_html([score], profile=LEGAL_PROFILE)
        assert 'class="para red"' in out

    def test_profile_name_appears_in_legend(self) -> None:
        out = render_heatmap_html([], profile=TECHNICAL_PROFILE)
        assert "technical" in out


# ---------------------------------------------------------------------------
# render_heatmap_markdown
# ---------------------------------------------------------------------------


class TestRenderHeatmapMarkdown:
    def test_header_includes_profile_and_thresholds(self, trio: list[ParagraphScore]) -> None:
        out = render_heatmap_markdown(trio, profile=LEGAL_PROFILE)
        assert "profile: `legal`" in out
        assert "0.90" in out
        assert "0.70" in out

    def test_empty_scores_renders_placeholder(self) -> None:
        out = render_heatmap_markdown([])
        assert "(no paragraphs to render)" in out

    def test_each_paragraph_wrapped_in_span(self, trio: list[ParagraphScore]) -> None:
        out = render_heatmap_markdown(trio)
        # One <span ...> per paragraph (3 total).
        assert out.count("<span style=") == 3
        assert out.count("</span>") == 3

    def test_classification_label_present(self, trio: list[ParagraphScore]) -> None:
        out = render_heatmap_markdown(trio, profile=LEGAL_PROFILE)
        assert "(green)" in out
        assert "(yellow)" in out
        assert "(red)" in out

    def test_confidence_displayed(self, trio: list[ParagraphScore]) -> None:
        out = render_heatmap_markdown(trio)
        assert "<b>0.95</b>" in out
        assert "<b>0.75</b>" in out
        assert "<b>0.40</b>" in out

    def test_paragraph_text_escaped(self) -> None:
        score = ParagraphScore(text='<script>evil()</script>', confidence=0.95)
        out = render_heatmap_markdown([score])
        assert "<script>evil()</script>" not in out
        assert "&lt;script&gt;" in out

    def test_color_changes_with_profile(self) -> None:
        # 0.65: yellow under LEGAL (red), yellow under TECHNICAL (yellow)
        score = ParagraphScore(text="x", confidence=0.65)
        legal_out = render_heatmap_markdown([score], profile=LEGAL_PROFILE)
        tech_out = render_heatmap_markdown([score], profile=TECHNICAL_PROFILE)
        assert "(red)" in legal_out
        assert "(yellow)" in tech_out

    def test_paragraph_order_preserved(self) -> None:
        scores = [
            ParagraphScore(text="first-paragraph", confidence=0.95),
            ParagraphScore(text="second-paragraph", confidence=0.75),
        ]
        out = render_heatmap_markdown(scores)
        assert out.index("first-paragraph") < out.index("second-paragraph")


# ---------------------------------------------------------------------------
# Cross-renderer consistency
# ---------------------------------------------------------------------------


class TestRendererConsistency:
    def test_both_renderers_handle_empty_input(self) -> None:
        # Neither should raise; both return non-empty strings.
        assert render_heatmap_html([])
        assert render_heatmap_markdown([])

    def test_both_classify_same_score_identically(self) -> None:
        score = ParagraphScore(text="ambiguous", confidence=0.72)
        html_out = render_heatmap_html([score], profile=LEGAL_PROFILE)
        md_out = render_heatmap_markdown([score], profile=LEGAL_PROFILE)
        # 0.72 in [0.70, 0.90) -> yellow under LEGAL
        assert 'class="para yellow"' in html_out
        assert "(yellow)" in md_out

    def test_html_escaping_consistent_across_renderers(self) -> None:
        score = ParagraphScore(text='<b>injected</b>', confidence=0.95)
        for out in (render_heatmap_html([score]), render_heatmap_markdown([score])):
            assert "<b>injected</b>" not in out
            assert "&lt;b&gt;injected&lt;/b&gt;" in out
