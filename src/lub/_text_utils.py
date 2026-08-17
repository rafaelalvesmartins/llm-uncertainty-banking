# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Shared text-normalisation helpers for ``lub``.

Several modules need to normalise free-form LLM output before comparing
it (string-equality clustering in semantic estimators, answer matching
in benchmark runners, True/False detection in :mod:`lub.uncertainty.p_true`).
Before this module they each defined a private ``_normalize`` whose
implementation drifted slightly from the others -- one stripped trailing
``.!?,``, another did only ``.strip().lower()``, a third was a regex
pipeline tuned for numeric answers.

This module consolidates the *simple* variants. The complex,
benchmark-specific normaliser in :mod:`lub.benchmarks.correctness`
(which strips punctuation around digits and keeps decimal separators)
is intentionally **not** replaced; it has different semantics and
its own tests.

Placed at the top of the package because both :mod:`lub.benchmarks`
and :mod:`lub.uncertainty` consume it, and the import-linter contract
forbids ``lub.uncertainty -> lub.benchmarks``.

These helpers are private to the package -- not in any public ``__all__``.
"""

from __future__ import annotations

__all__ = [
    "normalize_answer",
]

# Trailing punctuation that ``p_true`` historically stripped to robustly
# detect "True." vs "True" vs "True!" -- factored out so callers can
# request the same behaviour without duplicating the literal.
_TRAILING_PUNCT = ".!?,"


def normalize_answer(text: str, *, strip_trailing_punct: bool = False) -> str:
    """Return a lower-cased, whitespace-trimmed copy of ``text``.

    This is the canonical implementation of the trivial normalisation
    pattern (``text.strip().lower()``) that several estimator modules
    used to repeat inline.

    Args:
        text: The free-form string to normalise. ``None`` is not
            accepted -- pass ``""`` if you have a missing value.
        strip_trailing_punct: When ``True``, also remove any trailing
            characters in :data:`_TRAILING_PUNCT` (``.``, ``!``, ``?``,
            ``,``). Used by True/False detection in
            :mod:`lub.uncertainty.p_true` so that ``"True."`` and
            ``"True"`` compare equal.

    Returns:
        The normalised string.

    Examples:
        >>> normalize_answer("  Hello, World!  ")
        'hello, world!'
        >>> normalize_answer("  True.  ", strip_trailing_punct=True)
        'true'
        >>> normalize_answer("False!?,", strip_trailing_punct=True)
        'false'
    """
    out = text.strip().lower()
    if strip_trailing_punct:
        out = out.rstrip(_TRAILING_PUNCT)
    return out
