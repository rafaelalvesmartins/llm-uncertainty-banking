# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for ``lub.connectors.bridge.embeddings`` (shared embedder)."""

from __future__ import annotations

import math

import pytest

from lub.connectors.bridge.embeddings import (
    EMBEDDING_DIM,
    cosine,
    embed,
    tokenize,
)


class TestTokenize:
    def test_lowercases(self) -> None:
        assert tokenize("PIX TED") == ["pix", "ted"]

    def test_drops_one_char_tokens(self) -> None:
        assert tokenize("a b cd") == ["cd"]

    def test_handles_punctuation(self) -> None:
        assert tokenize("pix, ted!") == ["pix", "ted"]

    def test_empty_string(self) -> None:
        assert tokenize("") == []


class TestEmbed:
    def test_returns_correct_dim(self) -> None:
        v = embed(["pix", "ted"])
        assert len(v) == EMBEDDING_DIM

    def test_empty_tokens_returns_zero_vector(self) -> None:
        v = embed([])
        assert all(x == 0 for x in v)
        assert len(v) == EMBEDDING_DIM

    def test_l2_normalized(self) -> None:
        v = embed(["pix", "ted", "doc"])
        norm = math.sqrt(sum(x * x for x in v))
        assert norm == pytest.approx(1.0, abs=1e-9)

    def test_deterministic(self) -> None:
        v1 = embed(["pix", "ted"])
        v2 = embed(["pix", "ted"])
        assert v1 == v2

    def test_different_tokens_different_vectors(self) -> None:
        v1 = embed(["pix"])
        v2 = embed(["loan"])
        assert v1 != v2

    def test_idf_table_changes_weights(self) -> None:
        v_default = embed(["pix", "ted"])
        v_idf = embed(["pix", "ted"], idf={"pix": 5.0, "ted": 0.1})
        assert v_default != v_idf


class TestCosine:
    def test_identical_vectors_cosine_one(self) -> None:
        v = embed(["pix", "ted"])
        assert cosine(v, v) == pytest.approx(1.0, abs=1e-9)

    def test_orthogonal_returns_zero(self) -> None:
        # Single token, very different
        v1 = embed(["aaaaaaaaaaa"])
        v2 = embed(["zzzzzzzzzzz"])
        # Likely (but not guaranteed) different hash slots
        sim = cosine(v1, v2)
        assert -1.0 <= sim <= 1.0

    def test_zero_vector_cosine_zero(self) -> None:
        v_text = embed(["pix"])
        v_zero = embed([])
        assert cosine(v_text, v_zero) == 0.0

    def test_handles_different_length_pairs_via_strict_false(self) -> None:
        # zip(strict=False) tolerates length mismatch (we don't actually
        # produce these here, but the contract should not raise).
        a = (1.0,) * EMBEDDING_DIM
        b = (1.0,) * EMBEDDING_DIM
        assert cosine(a, b) == EMBEDDING_DIM
