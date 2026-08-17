# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for lub.challenge.context_autopilot.ejection."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from lub.challenge.context_autopilot.ejection import (
    EjectedTurn,
    EjectionScore,
    Turn,
    _historical_usefulness,
    _normalise_age,
    _persist_ejections,
    _similarity,
    eject_top_k,
    score_for_ejection,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_evidence_store():
    """Evidence store mock with embedding dim and a stubbed query()."""
    store = MagicMock()
    store.dim = 8
    store.query.return_value = []
    return store


@pytest.fixture
def in_memory_ledger():
    """A ledger-like object holding an in-memory sqlite connection
    with the cec_meta_outcomes table populated for join testing."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE cec_meta_outcomes (claim_id TEXT PRIMARY KEY, held_up INTEGER)"
    )
    conn.execute(
        "CREATE TABLE context_ejections ("
        "session_id TEXT, ejected_turn_id INTEGER, ejection_score REAL,"
        " similarity_term REAL, age_term REAL, usefulness_term REAL,"
        " threshold_at_eject REAL, ejected_at TEXT)"
    )
    conn.commit()
    ledger = SimpleNamespace(_conn=conn)
    yield ledger
    conn.close()


@pytest.fixture
def fake_embed():
    """Patch lub.evidence.store._embed to deterministic unit vectors.

    Returns the patcher mock so individual tests can program return values.
    The default returns the same vector for any input (similarity == 1.0)
    unless overridden in the test.
    """
    def _make_vec(text: str, dim: int) -> np.ndarray:
        # Deterministic per-text unit vector. Same text -> same vec.
        rng = np.random.default_rng(abs(hash(text)) % (2**32))
        v = rng.standard_normal(dim)
        return v / (np.linalg.norm(v) + 1e-12)

    with patch("lub.evidence.store._embed", side_effect=_make_vec) as m:
        yield m


@pytest.fixture
def sample_turns():
    return [
        Turn(turn_id=1, text="What is my credit limit?", age_in_turns=0),
        Turn(turn_id=2, text="When was my last deposit?", age_in_turns=3),
        Turn(turn_id=3, text="Show me the loan offer.", age_in_turns=7),
    ]


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_turn_defaults(self):
        t = Turn(turn_id=1, text="hi")
        assert t.turn_id == 1
        assert t.text == "hi"
        assert t.age_in_turns == 0

    def test_turn_is_frozen(self):
        t = Turn(turn_id=1, text="hi")
        with pytest.raises(Exception):
            t.turn_id = 2  # type: ignore[misc]

    def test_ejection_score_terms_sum_to_score(self):
        s = EjectionScore(
            turn_id=1,
            score=0.6,
            similarity_term=0.4,
            age_term=0.1,
            usefulness_term=0.1,
            similarity=0.2,
            age_normalised=0.5,
            historical_usefulness=0.5,
            alpha=0.5,
            beta=0.2,
            gamma=0.3,
        )
        # Three additive terms should equal score (within fp tolerance).
        assert pytest.approx(s.score, abs=1e-9) == (
            s.similarity_term + s.age_term + s.usefulness_term
        )

    def test_ejected_turn_default_metadata(self):
        score = EjectionScore(
            turn_id=1, score=0.5, similarity_term=0.3, age_term=0.1,
            usefulness_term=0.1, similarity=0.4, age_normalised=0.5,
            historical_usefulness=0.5, alpha=0.5, beta=0.2, gamma=0.3,
        )
        e = EjectedTurn(turn_id=1, score=score, threshold=0.3)
        assert e.text_snippet == ""
        assert e.metadata == {}


# ---------------------------------------------------------------------------
# _similarity
# ---------------------------------------------------------------------------


class TestSimilarity:
    def test_identical_text_yields_one(self, mock_evidence_store, fake_embed):
        sim = _similarity("hello world", "hello world", mock_evidence_store)
        assert sim == pytest.approx(1.0, abs=1e-6)

    def test_empty_text_returns_zero(self, mock_evidence_store, fake_embed):
        assert _similarity("", "query", mock_evidence_store) == 0.0
        assert _similarity("turn", "", mock_evidence_store) == 0.0

    def test_returns_float_in_range(self, mock_evidence_store, fake_embed):
        sim = _similarity("a different turn", "the query", mock_evidence_store)
        assert isinstance(sim, float)
        # Cosine of unit vectors is in [-1, 1].
        assert -1.0 - 1e-6 <= sim <= 1.0 + 1e-6


# ---------------------------------------------------------------------------
# _historical_usefulness
# ---------------------------------------------------------------------------


class TestHistoricalUsefulness:
    def test_empty_text_returns_prior(self, mock_evidence_store, in_memory_ledger):
        assert _historical_usefulness("", mock_evidence_store, in_memory_ledger) == 0.5

    def test_no_neighbours_returns_prior(self, mock_evidence_store, in_memory_ledger):
        mock_evidence_store.query.return_value = []
        assert _historical_usefulness("text", mock_evidence_store, in_memory_ledger) == 0.5

    def test_query_exception_returns_prior(self, mock_evidence_store, in_memory_ledger):
        mock_evidence_store.query.side_effect = RuntimeError("boom")
        assert _historical_usefulness("text", mock_evidence_store, in_memory_ledger) == 0.5

    def test_held_up_rate_from_meta_outcomes(self, mock_evidence_store, in_memory_ledger):
        # Seed meta outcomes: 2 held up, 1 not.
        in_memory_ledger._conn.executemany(
            "INSERT INTO cec_meta_outcomes (claim_id, held_up) VALUES (?, ?)",
            [("ans-A", 1), ("ans-B", 1), ("ans-C", 0)],
        )
        in_memory_ledger._conn.commit()

        n1 = SimpleNamespace(answer="ans-A", question="q1", correct=True)
        n2 = SimpleNamespace(answer="ans-B", question="q2", correct=True)
        n3 = SimpleNamespace(answer="ans-C", question="q3", correct=False)
        mock_evidence_store.query.return_value = [n1, n2, n3]

        rate = _historical_usefulness("anything", mock_evidence_store, in_memory_ledger)
        assert rate == pytest.approx(2.0 / 3.0)
        assert 0.0 <= rate <= 1.0

    def test_falls_back_to_neighbour_correctness(self, mock_evidence_store, in_memory_ledger):
        # No meta outcomes seeded -- usefulness must come from `correct`.
        n_ok = SimpleNamespace(answer="x", question="y", correct=True)
        n_bad = SimpleNamespace(answer="x2", question="y2", correct=False)
        mock_evidence_store.query.return_value = [n_ok, n_bad]
        rate = _historical_usefulness("q", mock_evidence_store, in_memory_ledger)
        assert rate == pytest.approx(0.5)

    def test_no_conn_returns_prior_when_no_correct_flag(self, mock_evidence_store):
        ledger = SimpleNamespace()  # no _conn at all
        n = SimpleNamespace(answer="x", question="y", correct=None)
        mock_evidence_store.query.return_value = [n]
        rate = _historical_usefulness("q", mock_evidence_store, ledger)
        assert rate == 0.5


# ---------------------------------------------------------------------------
# _normalise_age
# ---------------------------------------------------------------------------


class TestNormaliseAge:
    def test_empty_population(self):
        assert _normalise_age(5, []) == 0.0

    def test_zero_max(self):
        assert _normalise_age(0, [0, 0, 0]) == 0.0

    def test_normalised_in_unit_range(self):
        ages = [0, 5, 10]
        for a in ages:
            v = _normalise_age(a, ages)
            assert 0.0 <= v <= 1.0
        assert _normalise_age(10, ages) == 1.0
        assert _normalise_age(0, ages) == 0.0
        assert _normalise_age(5, ages) == 0.5

    def test_clamps_above_max(self):
        # If age exceeds the population max, result must still be <= 1.
        assert _normalise_age(20, [0, 5, 10]) == 1.0


# ---------------------------------------------------------------------------
# score_for_ejection
# ---------------------------------------------------------------------------


class TestScoreForEjection:
    def test_returns_ejection_score(
        self, mock_evidence_store, in_memory_ledger, fake_embed
    ):
        turn = Turn(turn_id=42, text="some turn", age_in_turns=2)
        out = score_for_ejection(
            turn, "current query", mock_evidence_store, in_memory_ledger,
            age_normaliser=10,
        )
        assert isinstance(out, EjectionScore)
        assert out.turn_id == 42

    def test_terms_sum_to_score(
        self, mock_evidence_store, in_memory_ledger, fake_embed
    ):
        turn = Turn(turn_id=1, text="some turn", age_in_turns=4)
        out = score_for_ejection(
            turn, "current query", mock_evidence_store, in_memory_ledger,
            alpha=0.5, beta=0.2, gamma=0.3, age_normaliser=10,
        )
        assert pytest.approx(out.score, abs=1e-9) == (
            out.similarity_term + out.age_term + out.usefulness_term
        )

    def test_similarity_and_usefulness_in_unit_range(
        self, mock_evidence_store, in_memory_ledger, fake_embed
    ):
        turn = Turn(turn_id=1, text="hello", age_in_turns=0)
        out = score_for_ejection(
            turn, "world", mock_evidence_store, in_memory_ledger, age_normaliser=1,
        )
        # similarity is cosine -> [-1, 1]; usefulness defaults to 0.5
        # and is otherwise a rate -> [0, 1]; age_normalised must be in [0,1].
        assert -1.0 - 1e-6 <= out.similarity <= 1.0 + 1e-6
        assert 0.0 <= out.historical_usefulness <= 1.0
        assert 0.0 <= out.age_normalised <= 1.0

    def test_negative_weight_raises(
        self, mock_evidence_store, in_memory_ledger, fake_embed
    ):
        turn = Turn(turn_id=1, text="hi", age_in_turns=0)
        with pytest.raises(ValueError, match="non-negative"):
            score_for_ejection(
                turn, "q", mock_evidence_store, in_memory_ledger, alpha=-0.1,
            )
        with pytest.raises(ValueError, match="non-negative"):
            score_for_ejection(
                turn, "q", mock_evidence_store, in_memory_ledger, beta=-1.0,
            )
        with pytest.raises(ValueError, match="non-negative"):
            score_for_ejection(
                turn, "q", mock_evidence_store, in_memory_ledger, gamma=-0.01,
            )

    def test_uses_defaults_when_none(
        self, mock_evidence_store, in_memory_ledger, fake_embed
    ):
        from lub.challenge.defaults import EJECTION_ALPHA, EJECTION_BETA, EJECTION_GAMMA

        turn = Turn(turn_id=1, text="hi", age_in_turns=0)
        out = score_for_ejection(turn, "q", mock_evidence_store, in_memory_ledger)
        assert out.alpha == pytest.approx(EJECTION_ALPHA)
        assert out.beta == pytest.approx(EJECTION_BETA)
        assert out.gamma == pytest.approx(EJECTION_GAMMA)

    def test_zero_weights_yield_zero_score(
        self, mock_evidence_store, in_memory_ledger, fake_embed
    ):
        turn = Turn(turn_id=1, text="hello", age_in_turns=5)
        out = score_for_ejection(
            turn, "world", mock_evidence_store, in_memory_ledger,
            alpha=0.0, beta=0.0, gamma=0.0, age_normaliser=10,
        )
        assert out.score == pytest.approx(0.0)
        assert out.similarity_term == 0.0
        assert out.age_term == 0.0
        assert out.usefulness_term == 0.0

    def test_age_normaliser_zero_falls_back_to_default(
        self, mock_evidence_store, in_memory_ledger, fake_embed
    ):
        # age_normaliser=0 should NOT divide-by-zero; falls back to /100.
        turn = Turn(turn_id=1, text="hi", age_in_turns=50)
        out = score_for_ejection(
            turn, "q", mock_evidence_store, in_memory_ledger,
            age_normaliser=0,
        )
        assert out.age_normalised == pytest.approx(0.5)

    def test_age_normaliser_clamps_to_one(
        self, mock_evidence_store, in_memory_ledger, fake_embed
    ):
        turn = Turn(turn_id=1, text="hi", age_in_turns=999)
        out = score_for_ejection(
            turn, "q", mock_evidence_store, in_memory_ledger, age_normaliser=10,
        )
        assert out.age_normalised == 1.0


# ---------------------------------------------------------------------------
# eject_top_k
# ---------------------------------------------------------------------------


class TestEjectTopK:
    def test_empty_turns_returns_empty(self, mock_evidence_store, in_memory_ledger):
        out = eject_top_k(
            [], "q", mock_evidence_store, in_memory_ledger, k=3, threshold=0.0,
        )
        assert out == []

    def test_negative_k_raises(self, mock_evidence_store, in_memory_ledger, sample_turns):
        with pytest.raises(ValueError, match="k must be non-negative"):
            eject_top_k(
                sample_turns, "q", mock_evidence_store, in_memory_ledger,
                k=-1, threshold=0.0,
            )

    def test_threshold_out_of_range_raises(
        self, mock_evidence_store, in_memory_ledger, sample_turns
    ):
        with pytest.raises(ValueError, match="threshold must be in"):
            eject_top_k(
                sample_turns, "q", mock_evidence_store, in_memory_ledger,
                k=1, threshold=-0.1,
            )
        with pytest.raises(ValueError, match="threshold must be in"):
            eject_top_k(
                sample_turns, "q", mock_evidence_store, in_memory_ledger,
                k=1, threshold=11.0,
            )

    def test_k_zero_returns_empty(
        self, mock_evidence_store, in_memory_ledger, sample_turns, fake_embed
    ):
        out = eject_top_k(
            sample_turns, "q", mock_evidence_store, in_memory_ledger,
            k=0, threshold=0.0,
        )
        assert out == []

    def test_threshold_filters_low_scores(
        self, mock_evidence_store, in_memory_ledger, sample_turns, fake_embed
    ):
        # Threshold at upper bound -- nothing should pass.
        out = eject_top_k(
            sample_turns, "q", mock_evidence_store, in_memory_ledger,
            k=3, threshold=10.0,
        )
        assert out == []

    def test_returns_at_most_k(
        self, mock_evidence_store, in_memory_ledger, sample_turns, fake_embed
    ):
        out = eject_top_k(
            sample_turns, "different query text", mock_evidence_store, in_memory_ledger,
            k=1, threshold=0.0,
        )
        assert len(out) <= 1
        for e in out:
            assert isinstance(e, EjectedTurn)
            assert e.score.score >= 0.0
            assert e.threshold == 0.0

    def test_sorted_descending_by_score(
        self, mock_evidence_store, in_memory_ledger, sample_turns, fake_embed
    ):
        out = eject_top_k(
            sample_turns, "completely unrelated question", mock_evidence_store,
            in_memory_ledger, k=3, threshold=0.0,
        )
        scores = [e.score.score for e in out]
        assert scores == sorted(scores, reverse=True)

    def test_snippet_truncated_at_200(
        self, mock_evidence_store, in_memory_ledger, fake_embed
    ):
        long_text = "x" * 500
        turns = [Turn(turn_id=1, text=long_text, age_in_turns=10)]
        out = eject_top_k(
            turns, "q", mock_evidence_store, in_memory_ledger,
            k=1, threshold=0.0,
        )
        assert len(out) == 1
        snippet = out[0].text_snippet
        assert len(snippet) == 200
        assert snippet.endswith("...")

    def test_short_snippet_not_truncated(
        self, mock_evidence_store, in_memory_ledger, fake_embed
    ):
        turns = [Turn(turn_id=1, text="short", age_in_turns=10)]
        out = eject_top_k(
            turns, "q", mock_evidence_store, in_memory_ledger,
            k=1, threshold=0.0,
        )
        assert out[0].text_snippet == "short"

    def test_metadata_recorded(
        self, mock_evidence_store, in_memory_ledger, sample_turns, fake_embed
    ):
        out = eject_top_k(
            sample_turns, "q", mock_evidence_store, in_memory_ledger,
            k=2, threshold=0.0,
        )
        for e in out:
            assert e.metadata["k"] == 2
            assert e.metadata["n_candidates"] == len(sample_turns)

    def test_persist_writes_rows(
        self, mock_evidence_store, in_memory_ledger, sample_turns, fake_embed
    ):
        out = eject_top_k(
            sample_turns, "q", mock_evidence_store, in_memory_ledger,
            k=3, threshold=0.0, session_id="sess-1", persist=True,
        )
        rows = in_memory_ledger._conn.execute(
            "SELECT session_id, ejected_turn_id FROM context_ejections"
        ).fetchall()
        assert len(rows) == len(out)
        for r in rows:
            assert r[0] == "sess-1"

    def test_persist_false_writes_no_rows(
        self, mock_evidence_store, in_memory_ledger, sample_turns, fake_embed
    ):
        eject_top_k(
            sample_turns, "q", mock_evidence_store, in_memory_ledger,
            k=3, threshold=0.0, session_id="sess-1", persist=False,
        )
        rows = in_memory_ledger._conn.execute(
            "SELECT COUNT(*) FROM context_ejections"
        ).fetchone()
        assert rows[0] == 0

    def test_no_session_id_writes_no_rows(
        self, mock_evidence_store, in_memory_ledger, sample_turns, fake_embed
    ):
        eject_top_k(
            sample_turns, "q", mock_evidence_store, in_memory_ledger,
            k=3, threshold=0.0, session_id=None, persist=True,
        )
        rows = in_memory_ledger._conn.execute(
            "SELECT COUNT(*) FROM context_ejections"
        ).fetchone()
        assert rows[0] == 0


# ---------------------------------------------------------------------------
# _persist_ejections direct test
# ---------------------------------------------------------------------------


class TestPersistEjections:
    def test_inserts_one_row_per_ejection(self, in_memory_ledger):
        score = EjectionScore(
            turn_id=7, score=0.42, similarity_term=0.3, age_term=0.1,
            usefulness_term=0.02, similarity=0.4, age_normalised=0.5,
            historical_usefulness=0.5, alpha=0.5, beta=0.2, gamma=0.3,
        )
        ejected = [EjectedTurn(turn_id=7, score=score, threshold=0.1)]
        _persist_ejections(in_memory_ledger, "abc", ejected)
        rows = in_memory_ledger._conn.execute(
            "SELECT session_id, ejected_turn_id, ejection_score,"
            " similarity_term, age_term, usefulness_term, threshold_at_eject"
            " FROM context_ejections"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "abc"
        assert rows[0][1] == 7
        assert rows[0][2] == pytest.approx(0.42)
        assert rows[0][6] == pytest.approx(0.1)
