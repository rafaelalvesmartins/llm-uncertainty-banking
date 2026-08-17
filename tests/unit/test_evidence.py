# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from lub.evidence.store import EvidenceStore, Neighbour, retrieval_adjusted
from lub.types import UncertaintyResult


def test_add_and_query_returns_topk_by_similarity() -> None:
    s = EvidenceStore()
    s.add("what is basel iii cet1 minimum", "4.5 percent", correct=True)
    s.add("capital of france", "paris", correct=True)
    s.add("basel iii capital requirement", "varies", correct=False)
    hits = s.query("basel iii cet1", k=2)
    assert len(hits) == 2
    assert all(isinstance(h, Neighbour) for h in hits)
    # Most similar hit must be basel-related, not the paris one.
    assert "basel" in hits[0].question.lower()


def test_query_rejects_nonpositive_k() -> None:
    s = EvidenceStore()
    s.add("q", "a", correct=True)
    with pytest.raises(ValueError, match="positive"):
        s.query("q", k=0)


def test_empty_store_returns_empty_list() -> None:
    assert EvidenceStore().query("anything", k=5) == []


def test_retrieval_adjusted_pulls_toward_correct_rate() -> None:
    res = UncertaintyResult(answer="x", confidence=0.2)
    neighbours = [
        Neighbour(question="q", answer="a", correct=True, cosine_similarity=0.9),
        Neighbour(question="q", answer="a", correct=True, cosine_similarity=0.8),
        Neighbour(question="q", answer="a", correct=False, cosine_similarity=0.7),
    ]
    adjusted = retrieval_adjusted(res, neighbours, weight=0.5)
    # correct_rate = 2/3, blend half -> 0.5*0.2 + 0.5*(2/3) ≈ 0.4333
    assert adjusted.confidence == pytest.approx(0.1 + 1.0 / 3, abs=1e-6)


def test_retrieval_adjusted_passthrough_when_weight_zero() -> None:
    res = UncertaintyResult(answer="x", confidence=0.42)
    adjusted = retrieval_adjusted(
        res, [Neighbour(question="q", answer="a", correct=True, cosine_similarity=1.0)], weight=0.0
    )
    assert adjusted.confidence == pytest.approx(0.42)


def test_retrieval_adjusted_no_neighbours_returns_identity() -> None:
    res = UncertaintyResult(answer="x", confidence=0.42)
    adjusted = retrieval_adjusted(res, [], weight=0.9)
    assert adjusted is res


def test_save_and_load_round_trip() -> None:
    s = EvidenceStore()
    s.add("alpha question", "aa", correct=True)
    s.add("bravo question", "bb", correct=False)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "store.npz"
        s.save(path)
        s2 = EvidenceStore.load(path)
        assert len(s2) == 2
        hits = s2.query("alpha question", k=1)
        assert hits[0].question == "alpha question"
        assert hits[0].correct is True
