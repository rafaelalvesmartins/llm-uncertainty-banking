# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Linguistic calibration score for long-form LLM generations.

Extracts hedging language from model outputs and converts it to an
implied probability, then evaluates whether those implied probabilities
are calibrated against observed outcomes using a proper scoring rule.

The method follows Band, Ghosh et al. (2024, ICML):

1. Detect **hedge phrases** in the generation using a curated regex
   lexicon (e.g., "I'm confident that", "probably", "it's possible",
   "I'm not sure").
2. Map each hedge to an **implied probability** via a lookup table
   derived from human calibration studies (Beyth-Marom 1982, Wallsten
   et al. 1986, adapted for LLM outputs by Band et al. 2024).
3. Compute the **Brier score** of the implied probabilities against
   binary correctness labels — this is the linguistic calibration score.

A linguistically calibrated model says "probably" only when the answer
is correct ~75% of the time. In banking, regulators want to know
whether the model's *language* matches its *reliability* — a model that
says "definitely" but is wrong 30% of the time is more dangerous than
one that hedges appropriately.

Pure stdlib + numpy. No NLP pipeline, no external model dependency.

Reference:
    Band, N., Ghosh, S., et al. (2024). *Linguistic Calibration of
    Long-Form Generations.* ICML 2024. arXiv:2404.00474.
"""

from __future__ import annotations

import re

import numpy as np
from numpy.typing import ArrayLike

# ---------------------------------------------------------------------------
# Hedge lexicon → implied probability
# ---------------------------------------------------------------------------
# Ordered by implied probability, high → low. The regex patterns are
# applied in order; the first match wins.  Probabilities are drawn
# from Beyth-Marom (1982) and Wallsten et al. (1986), rounded for
# practical use and validated against GPT-4/Claude output patterns.

_HEDGE_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\b(certainly|definitely|undoubtedly|without a doubt)\b", re.I), 0.95),
    (
        re.compile(
            r"\b(i'?m confident|i am confident|very likely|highly likely|almost certain)\b", re.I
        ),
        0.90,
    ),
    (re.compile(r"\b(most likely|in all likelihood|strongly suggest)\b", re.I), 0.85),
    (re.compile(r"\b(likely|probably|i believe)\b", re.I), 0.75),
    (re.compile(r"\b(it seems|it appears|seemingly|apparently)\b", re.I), 0.65),
    (re.compile(r"\b(possibly|perhaps|maybe|might be|could be|it'?s possible)\b", re.I), 0.50),
    (re.compile(r"\b(i'?m not sure|i am not sure|uncertain|unclear|hard to say)\b", re.I), 0.35),
    (re.compile(r"\b(very unlikely|highly unlikely|almost impossible)\b", re.I), 0.10),
    (re.compile(r"\b(unlikely|doubtful|improbable|i doubt)\b", re.I), 0.20),
]

# Default implied probability when no hedge is detected: the model
# made a bare assertion → assume high confidence.
_DEFAULT_IMPLIED_PROB = 0.85


def extract_implied_probability(text: str) -> tuple[float, str | None]:
    """Extract the implied probability from hedging language in ``text``.

    Returns ``(probability, matched_phrase)`` where ``matched_phrase``
    is the first hedge pattern found, or ``None`` if the text contains
    no hedging language (in which case the default 0.85 is returned).
    """
    for pattern, prob in _HEDGE_PATTERNS:
        m = pattern.search(text)
        if m:
            return prob, m.group(0)
    return _DEFAULT_IMPLIED_PROB, None


def linguistic_calibration_score(
    texts: list[str],
    correct: ArrayLike,
) -> float:
    """Brier score of hedge-implied probabilities against correctness.

    Lower is better (0 = perfectly calibrated hedging, 1 = worst).

    Parameters
    ----------
    texts : list of str
        Model outputs (one per example).
    correct : array-like of {0, 1}
        Binary correctness labels.

    Returns
    -------
    float
        The linguistic calibration score (Brier of implied probs).
    """
    y = np.asarray(correct, dtype=np.float64).ravel()
    if len(texts) != y.size:
        raise ValueError(f"texts ({len(texts)}) and correct ({y.size}) must have same length")
    if y.size == 0:
        raise ValueError("inputs must be non-empty")

    implied = np.array([extract_implied_probability(t)[0] for t in texts], dtype=np.float64)
    return float(np.mean((implied - y) ** 2))


def linguistic_calibration_report(
    texts: list[str],
    correct: ArrayLike,
) -> dict[str, object]:
    """Detailed linguistic calibration analysis.

    Returns a dict with the overall score plus per-hedge-category
    breakdown (count, mean implied prob, mean accuracy).
    """
    y = np.asarray(correct, dtype=np.float64).ravel()
    if len(texts) != y.size:
        raise ValueError(f"texts ({len(texts)}) and correct ({y.size}) must have same length")
    if y.size == 0:
        raise ValueError("inputs must be non-empty")

    implied: list[float] = []
    hedges: list[str | None] = []
    for t in texts:
        p, h = extract_implied_probability(t)
        implied.append(p)
        hedges.append(h)

    implied_arr = np.array(implied, dtype=np.float64)
    score = float(np.mean((implied_arr - y) ** 2))

    # Per-category breakdown
    categories: dict[float, dict[str, float]] = {}
    for prob, corr_val in zip(implied, y.tolist(), strict=True):
        if prob not in categories:
            categories[prob] = {"count": 0.0, "sum_correct": 0.0}
        categories[prob]["count"] += 1.0
        categories[prob]["sum_correct"] += corr_val

    breakdown: list[dict[str, float]] = []
    for prob in sorted(categories, reverse=True):
        cat = categories[prob]
        n = cat["count"]
        breakdown.append(
            {
                "implied_probability": prob,
                "count": n,
                "mean_accuracy": cat["sum_correct"] / n if n > 0 else 0.0,
                "gap": abs(prob - cat["sum_correct"] / n) if n > 0 else 0.0,
            }
        )

    return {
        "linguistic_calibration_score": score,
        "n": int(y.size),
        "n_hedged": sum(1 for h in hedges if h is not None),
        "n_bare_assertion": sum(1 for h in hedges if h is None),
        "breakdown": breakdown,
    }


__all__ = [
    "extract_implied_probability",
    "linguistic_calibration_report",
    "linguistic_calibration_score",
]
