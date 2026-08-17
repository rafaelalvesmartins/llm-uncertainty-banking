# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""lub.cnh -- Calibrated Narrative Heatmap.

Renders a per-paragraph calibrated-confidence heatmap on AI-assisted text.
Each paragraph (or sentence) gets a confidence score; a CSS gradient
(green -> yellow -> red) makes uncertain sentences visible to the human
reviewer.

5th "first OSS" claim candidate (counsel-gated). Spec:
``planning/26_CNH_Calibrated_Narrative_Heatmap_2026-04-25.md``.

This module is **purely additive**: it depends on `lub.uncertainty`
indirectly (via duck-typed estimator interface) but does not modify any
L1-L5 module. ``python-docx`` is intentionally NOT a hard dependency; the
docx renderer is a future extra.
"""

from __future__ import annotations

from lub.cnh.heatmap import render_heatmap_html, render_heatmap_markdown
from lub.cnh.score import ParagraphScore, score_paragraphs
from lub.cnh.thresholds import (
    CASUAL_PROFILE,
    LEGAL_LIKE_PROFILES,
    LEGAL_PROFILE,
    MARKETING_LIKE_PROFILES,
    MARKETING_PROFILE,
    TECHNICAL_LIKE_PROFILES,
    TECHNICAL_PROFILE,
    DomainProfile,
    classify,
    profile_for_context,
)

__all__ = [
    # Score
    "ParagraphScore",
    "score_paragraphs",
    # Thresholds
    "DomainProfile",
    "LEGAL_PROFILE",
    "TECHNICAL_PROFILE",
    "MARKETING_PROFILE",
    "CASUAL_PROFILE",
    "LEGAL_LIKE_PROFILES",
    "TECHNICAL_LIKE_PROFILES",
    "MARKETING_LIKE_PROFILES",
    "classify",
    "profile_for_context",
    # Render
    "render_heatmap_html",
    "render_heatmap_markdown",
]
