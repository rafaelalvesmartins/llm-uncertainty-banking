# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for lub._text_utils.normalize_answer.

The helper consolidates the simple variants of the inline ``_normalize``
that several estimators used to define privately. These tests pin down
the behaviour against the original inline implementations so the
extraction stays drift-free.
"""

from __future__ import annotations

import pytest

from lub._text_utils import normalize_answer

# ---------------------------------------------------------------------------
# Default mode (matches old _normalize in self_consistency / epistemic_aleatoric /
# the string-equality fallback in semantic_entropy)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Hello", "hello"),
        ("  Hello  ", "hello"),
        ("PARIS", "paris"),
        ("MiXeD cAsE", "mixed case"),
        ("", ""),
        ("   ", ""),
        ("ALREADY-LOWERCASE", "already-lowercase"),
        ("\tTabbed\t", "tabbed"),
    ],
)
def test_default_mode_matches_strip_lower(raw: str, expected: str) -> None:
    assert normalize_answer(raw) == expected


def test_default_mode_keeps_internal_punctuation() -> None:
    """Default mode must NOT strip trailing punctuation -- self_consistency
    relied on 'Yes!' being a different bucket from 'Yes' before this
    extraction. Document the invariant."""
    assert normalize_answer("Yes!") == "yes!"
    assert normalize_answer("Yes.") == "yes."


# ---------------------------------------------------------------------------
# strip_trailing_punct mode (matches old p_true._normalize)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("True.", "true"),
        ("True", "true"),
        ("True!", "true"),
        ("True?", "true"),
        ("True,", "true"),
        ("False!?,", "false"),
        ("  False.  ", "false"),
        ("yes,", "yes"),
        ("no", "no"),
        ("", ""),
    ],
)
def test_strip_trailing_punct_mode(raw: str, expected: str) -> None:
    assert normalize_answer(raw, strip_trailing_punct=True) == expected


def test_strip_trailing_punct_only_strips_trailing() -> None:
    """Internal punctuation must survive."""
    assert normalize_answer("It's True.", strip_trailing_punct=True) == "it's true"


def test_strip_trailing_punct_does_not_change_default_behaviour_when_no_punct() -> None:
    """For a string without trailing punctuation, both modes must agree."""
    assert (
        normalize_answer("hello world")
        == normalize_answer("hello world", strip_trailing_punct=True)
    )


def test_strip_trailing_punct_equivalent_to_old_inline_implementation() -> None:
    """Verify bit-for-bit equivalence with p_true.py:48-49 before the refactor."""
    def old_p_true_normalize(text: str) -> str:
        return text.strip().lower().rstrip(".!?,")

    for s in ["True.", "  False!  ", "yes!?,", "no", "True", "Mixed.case.dots."]:
        assert (
            normalize_answer(s, strip_trailing_punct=True) == old_p_true_normalize(s)
        ), f"mismatch on input {s!r}"
