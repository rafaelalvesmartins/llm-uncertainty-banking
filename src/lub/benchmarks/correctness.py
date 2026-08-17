# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Correctness scorers for the benchmark runner.

Pluggable ``(pred: str, gold: str) -> bool`` callables that the
:class:`~lub.benchmarks.runner.BenchmarkRunner` uses to decide whether a
generated answer matches the dataset's gold label.

Three families ship here:

* :func:`exact_match` — numeric-aware exact string match. The default.
* :func:`fuzzy_match` — substring containment with numeric fallback,
  for verbose LLM completions against short gold labels.
* :func:`choice_match` — factory for classification-task scorers in the
  PIXIU / FLARE convention.

The whole module is pure stdlib — no NumPy, no torch — so a model-risk
reviewer can audit a correctness decision end-to-end without pulling in
the broader scientific stack.

Extracted from ``lub.benchmarks.runner`` in the 2026-04-25 refactor
program (ADR-005, Fase 6). ``runner.py`` re-exports every name in this
module so existing imports (``from lub.benchmarks.runner import
exact_match``) continue to work.
"""

from __future__ import annotations

import re
import string
from collections.abc import Callable, Mapping, Sequence

CorrectnessFn = Callable[[str, str], bool]
"""Signature for a correctness scorer: ``(prediction, gold) -> bool``."""


_PUNCT_KEEP_NUM = set(".,")  # keep digits' decorators for numeric parsing
_PUNCT_RE = re.compile(
    "[" + re.escape("".join(c for c in string.punctuation if c not in _PUNCT_KEEP_NUM)) + "]"
)
_NUMERIC_RE = re.compile(r"^-?\d+(?:[.,]\d+)*(?:\.\d+)?%?$")


def _normalize(text: str) -> str:
    """Normalize an answer string for exact-match comparison.

    Punctuation other than ``.`` and ``,`` is replaced with spaces and
    collapsed; the remaining punctuation is kept so that decimal points in
    numeric answers survive. The numeric parser in :func:`exact_match`
    handles the ``.`` / ``,`` ambiguity separately.
    """
    lowered = text.strip().lower()
    no_punct = _PUNCT_RE.sub(" ", lowered)
    return " ".join(no_punct.split())


def _as_number(text: str) -> float | None:
    """Parse ``text`` as a number, tolerating ``,`` thousand separators and ``%``.

    Returns ``None`` if the string does not look like a plain number.
    Handles the three most common financial-answer shapes:

    - ``"4.5"``, ``"4.5%"`` → ``4.5``
    - ``"1,234"`` → ``1234.0``
    - ``"1,234.50"`` → ``1234.5``

    Does not try to distinguish European decimal comma from US thousand
    separator — FinQA and TAT-QA are US English datasets.
    """
    t = text.strip()
    if not t:
        return None
    if not _NUMERIC_RE.match(t):
        return None
    t = t.rstrip("%").replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def exact_match(pred: str, gold: str) -> bool:
    """Default correctness: numeric-aware exact string match.

    Numeric answers are compared by value (``float`` equality within
    ``1e-9``) so that ``"1,234.50"`` and ``"1234.5"`` and ``"1234.50%"``
    no longer disagree after normalization. Non-numeric answers fall back
    to the punctuation-stripped, lower-cased, whitespace-collapsed form.
    """
    pred_num = _as_number(pred)
    gold_num = _as_number(gold)
    if pred_num is not None and gold_num is not None:
        return abs(pred_num - gold_num) < 1e-9
    return _normalize(pred) == _normalize(gold)


def fuzzy_match(pred: str, gold: str) -> bool:
    """Lenient correctness: gold answer appears as substring of prediction.

    LLMs produce verbose answers ("The minimum CET1 ratio is 4.5% under
    Basel III...") while gold answers are short ("4.5%"). This scorer
    checks whether the normalized gold answer appears anywhere in the
    normalized prediction, or whether both parse to the same number.

    Falls back to exact_match for short gold answers that could
    spuriously match (e.g., single digits).
    """
    # Try numeric match first
    pred_num = _as_number(pred)
    gold_num = _as_number(gold)
    if pred_num is not None and gold_num is not None:
        return abs(pred_num - gold_num) < 1e-9

    gold_norm = _normalize(gold)
    pred_norm = _normalize(pred)

    # Exact match
    if pred_norm == gold_norm:
        return True

    # Substring containment (gold in pred)
    if len(gold_norm) >= 3 and gold_norm in pred_norm:
        return True

    # Check if the gold answer's numeric part appears in the prediction
    gold_num_in_text = _as_number(gold.strip().rstrip(".").rstrip(","))
    if gold_num_in_text is not None:
        # Search for the number anywhere in the prediction
        for token in pred.split():
            token_num = _as_number(token.strip(".,;:()"))
            if token_num is not None and abs(token_num - gold_num_in_text) < 1e-9:
                return True

    return False


def choice_match(
    choices: Sequence[str],
    synonyms: Mapping[str, Sequence[str]] | None = None,
    default: str | None = None,
) -> CorrectnessFn:
    """Build a correctness function for classification tasks.

    Follows the PIXIU / FLARE ``Classification.process_results`` convention:
    the prediction is considered correct if, after lower-casing, it
    contains any of the gold choice's tokens (or any of the gold choice's
    declared synonyms). If no choice matches, the prediction is marked
    incorrect and — when used with :class:`BenchmarkRunner` — counts toward
    the ``missing_ratio`` metric via the pluggable correctness path.

    Parameters
    ----------
    choices:
        The canonical class labels for the task (e.g. ``("positive",
        "negative", "neutral")``). Matching is case-insensitive.
    synonyms:
        Optional ``canonical -> [accepted phrases]`` mapping. Used when
        the gold label has common surface variants that the model may
        produce instead (e.g. PIXIU's ``rise -> ("yes", "positive")``).
        Phrases are matched case-insensitively as substrings of the
        prediction.
    default:
        Optional fallback choice applied when the prediction matches
        none of the choices and none of the synonyms. When supplied,
        the prediction is treated as if the model had emitted ``default``.
        Use sparingly — silently defaulting can mask real refusals.

    Returns
    -------
    CorrectnessFn
        A ``(pred, gold) -> bool`` callable suitable for
        :class:`BenchmarkRunner(correctness_fn=...)`.
    """
    syn_lower: dict[str, list[str]] = {}
    for canonical, phrases in (synonyms or {}).items():
        key = canonical.strip().lower()
        syn_lower[key] = [p.strip().lower() for p in phrases if p.strip()]

    choices_lower = [c.strip().lower() for c in choices]
    default_lower = default.strip().lower() if default is not None else None

    def _match(pred: str, gold: str) -> bool:
        p = pred.strip().lower()
        g = gold.strip().lower()
        # 1. Direct substring against every choice (PIXIU-style).
        matched: str | None = None
        for choice in choices_lower:
            if choice and choice in p:
                matched = choice
                break
        # 2. Synonym fallback — the first synonym that matches "votes"
        #    for its canonical label.
        if matched is None:
            for canonical, phrases in syn_lower.items():
                for phrase in phrases:
                    if phrase and phrase in p:
                        matched = canonical
                        break
                if matched is not None:
                    break
        # 3. Default fallback — treat the prediction as ``default``.
        if matched is None and default_lower is not None:
            matched = default_lower
        if matched is None:
            return False
        return matched == g

    return _match


__all__ = [
    "CorrectnessFn",
    "choice_match",
    "exact_match",
    "fuzzy_match",
]
