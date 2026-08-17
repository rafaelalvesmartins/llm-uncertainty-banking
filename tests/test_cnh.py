# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""Tests for lub.cnh (Calibrated Narrative Heatmap, pass 44).

Spec: planning/26_CNH_Calibrated_Narrative_Heatmap_2026-04-25.md.
"""

from __future__ import annotations

import re

import pytest

from lub.cnh import (
    CASUAL_PROFILE,
    LEGAL_PROFILE,
    MARKETING_PROFILE,
    TECHNICAL_PROFILE,
    DomainProfile,
    ParagraphScore,
    classify,
    profile_for_context,
    render_heatmap_html,
    render_heatmap_markdown,
    score_paragraphs,
)
from lub.cnh.score import split_paragraphs

# ---------------------------------------------------------------------------
# DomainProfile + thresholds
# ---------------------------------------------------------------------------


def test_domain_profile_validates_ordering():
    with pytest.raises(ValueError, match="must satisfy"):
        DomainProfile(name="bad", green_min=0.5, yellow_min=0.7)


def test_four_profile_presets_in_strictest_to_loosest_order():
    assert LEGAL_PROFILE.green_min > TECHNICAL_PROFILE.green_min
    assert TECHNICAL_PROFILE.green_min > MARKETING_PROFILE.green_min
    assert MARKETING_PROFILE.green_min > CASUAL_PROFILE.green_min


def test_classify_routes_to_three_buckets():
    assert classify(0.95, LEGAL_PROFILE) == "green"
    assert classify(0.75, LEGAL_PROFILE) == "yellow"
    assert classify(0.50, LEGAL_PROFILE) == "red"


def test_profile_for_context_resolves_names():
    assert profile_for_context("petition") is LEGAL_PROFILE
    assert profile_for_context("technical") is TECHNICAL_PROFILE
    assert profile_for_context("outreach") is MARKETING_PROFILE
    assert profile_for_context("blog") is CASUAL_PROFILE
    assert profile_for_context(None) is CASUAL_PROFILE


# ---------------------------------------------------------------------------
# split_paragraphs + score_paragraphs
# ---------------------------------------------------------------------------


def test_split_paragraphs_handles_blank_lines():
    text = "Para one.\n\nPara two has\nmultiple lines.\n\n\nPara three."
    parts = split_paragraphs(text)
    assert parts == ["Para one.", "Para two has\nmultiple lines.", "Para three."]


def test_score_paragraphs_with_simple_scorer():
    def scorer(p):
        pl = p.lower()
        if re.search(r"\bgreen\b", pl):
            return 0.95
        if re.search(r"\byellow\b", pl):
            return 0.55
        return 0.20

    text = "Status green: all good.\n\nStatus yellow: review needed.\n\nFinal status."
    scores = score_paragraphs(text, scorer)
    assert len(scores) == 3
    assert scores[0].confidence == pytest.approx(0.95)
    assert scores[1].confidence == pytest.approx(0.55)
    assert scores[2].confidence == pytest.approx(0.20)


def test_score_paragraphs_honors_tuple_return():
    def fused(p):
        return (0.85, {"p_true": 0.8, "logprob": 0.9})

    s = score_paragraphs("Test.", fused)
    assert s[0].confidence == pytest.approx(0.85)
    assert s[0].method_breakdown == {"p_true": 0.8, "logprob": 0.9}


def test_score_paragraphs_fails_closed_on_scorer_exception():
    def bad(p):
        raise RuntimeError("oops")

    s = score_paragraphs("Test.", bad)
    assert s[0].confidence == 0.0


def test_score_paragraphs_clamps_to_unit_interval():
    s = score_paragraphs("X.\n\nY.", lambda p: 1.5 if "X" in p else -0.3)
    assert s[0].confidence == 1.0
    assert s[1].confidence == 0.0


# ---------------------------------------------------------------------------
# render_heatmap_html + render_heatmap_markdown
# ---------------------------------------------------------------------------


def _three_color_scores():
    return [
        ParagraphScore(text="green para", confidence=0.95),
        ParagraphScore(text="yellow para", confidence=0.55),
        ParagraphScore(text="red para", confidence=0.20),
    ]


def test_render_heatmap_html_three_colors_under_casual():
    out = render_heatmap_html(_three_color_scores(), profile=CASUAL_PROFILE)
    assert out.startswith("<!DOCTYPE html>")
    assert "</html>" in out
    classes = re.findall(r'class="para (\w+)"', out)
    assert "green" in classes and "yellow" in classes and "red" in classes


def test_render_heatmap_markdown_three_colors_under_casual():
    out = render_heatmap_markdown(_three_color_scores(), profile=CASUAL_PROFILE)
    assert "(green)" in out and "(yellow)" in out and "(red)" in out
    assert "0.95" in out and "0.55" in out and "0.20" in out


def test_render_heatmap_html_empty_state():
    out = render_heatmap_html([])
    assert "No paragraphs to render" in out


def test_render_heatmap_markdown_empty_state():
    out = render_heatmap_markdown([])
    assert "no paragraphs" in out.lower()


def test_render_heatmap_html_escapes_xss():
    scores = [ParagraphScore(text="<script>alert(1)</script>", confidence=0.9)]
    out = render_heatmap_html(scores)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_profile_aware_classification_changes_color():
    """Same confidence, different profile -> different bucket."""
    s = [ParagraphScore(text="x", confidence=0.55)]
    assert "para red" in render_heatmap_html(s, profile=LEGAL_PROFILE)
    assert "para yellow" in render_heatmap_html(s, profile=CASUAL_PROFILE)


def test_render_heatmap_html_includes_profile_legend():
    out = render_heatmap_html(_three_color_scores(), profile=LEGAL_PROFILE)
    assert "legal" in out  # profile name in legend
    assert "0.90" in out  # green_min from LEGAL
    assert "0.70" in out  # yellow_min from LEGAL
