# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""lub.cnh.score -- per-paragraph confidence scoring.

Splits AI-assisted text into paragraphs (default: blank-line split) and
runs each through a duck-typed scorer callable. The scorer can be a real
:class:`~lub.uncertainty.base.Estimator`, a fused
:class:`~lub.orchestration.swarm.UQSwarm`, or any callable that takes a
string and returns a float in [0, 1].

Spec: planning/26_CNH_Calibrated_Narrative_Heatmap_2026-04-25.md §3.1.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

__all__ = ["ParagraphScore", "score_paragraphs", "split_paragraphs"]


# A scorer is anything callable that accepts a string and returns either
# a float in [0, 1] OR a (float, dict) tuple where the dict is the
# method-breakdown.
Scorer = Callable[[str], Any]


@dataclass(frozen=True)
class ParagraphScore:
    """One paragraph's worth of calibrated narrative score.

    Frozen so it can be cached + serialized cleanly. The
    ``method_breakdown`` dict is the per-estimator confidences if a
    fused scorer was used; for single-estimator scorers it has one entry.
    """

    text: str
    confidence: float
    method_breakdown: dict[str, float] = field(default_factory=dict)


def split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs.

    Default rule: split on one-or-more blank lines (``\\n\\s*\\n``).
    Strips surrounding whitespace from each paragraph and drops empty ones.
    """
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def _coerce_score(raw: Any, fallback_method: str = "scorer") -> tuple[float, dict[str, float]]:
    """Normalize scorer return values into (confidence, breakdown)."""
    if isinstance(raw, tuple) and len(raw) == 2:
        confidence, breakdown = raw
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        if not isinstance(breakdown, dict):
            breakdown = {fallback_method: confidence}
        return _clamp01(confidence), {k: _clamp01(float(v)) for k, v in breakdown.items()}
    try:
        confidence = float(raw)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = _clamp01(confidence)
    return confidence, {fallback_method: confidence}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def score_paragraphs(
    text: str,
    scorer: Scorer,
    *,
    splitter: Callable[[str], Iterable[str]] | None = None,
) -> list[ParagraphScore]:
    """Score every paragraph in ``text`` via ``scorer``.

    Args:
        text: AI-assisted text (markdown or plain) to score.
        scorer: Any callable that accepts a paragraph string and returns
            a float in [0, 1] OR a (float, dict[str, float]) tuple.
        splitter: Optional custom splitter; defaults to
            :func:`split_paragraphs`. Pass a sentence splitter (e.g.
            spaCy's) for finer-grained heatmaps.

    Returns:
        List of :class:`ParagraphScore`, in the same order as the
        paragraphs in the input text.
    """
    if splitter is None:
        splitter = split_paragraphs
    paragraphs = list(splitter(text))
    scores: list[ParagraphScore] = []
    for p in paragraphs:
        try:
            raw = scorer(p)
        except Exception:  # noqa: BLE001 -- never crash the heatmap on a bad scorer
            raw = 0.0
        confidence, breakdown = _coerce_score(raw)
        scores.append(ParagraphScore(text=p, confidence=confidence, method_breakdown=breakdown))
    return scores
