# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Unit tests for :mod:`lub.challenge.context_autopilot.ejection`.

Spec: planning/25_Context_Autopilot_Spec_2026-04-25.md section 1.2.
"""

from __future__ import annotations

import pytest

from lub.challenge.context_autopilot import (
    EjectedTurn,
    EjectionScore,
    Turn,
    eject_top_k,
    score_for_ejection,
)
from lub.evidence import EvidenceStore
from lub.ledger import Ledger


def _seed_evidence(store: EvidenceStore) -> None:
    store.add("kyc rules for retail accounts", "yes", correct=True)
    store.add("aml threshold review", "no", correct=False)


def test_score_for_ejection_returns_dataclass() -> None:
    with Ledger(":memory:") as led:
        store = EvidenceStore()
        _seed_evidence(store)
        t = Turn(turn_id=0, text="aml threshold review", age_in_turns=2)
        s = score_for_ejection(t, "current question", store, led)
        assert isinstance(s, EjectionScore)
        assert s.turn_id == 0
        # similarity_term + age_term + usefulness_term == score (exactly).
        assert s.score == pytest.approx(
            s.similarity_term + s.age_term + s.usefulness_term
        )


def test_similar_turn_gets_lower_score_than_dissimilar_turn() -> None:
    """The similarity term penalises NON-similar turns -- so a turn very
    similar to the current query has a *low* (1 - similarity) and
    therefore a smaller similarity contribution."""
    with Ledger(":memory:") as led:
        store = EvidenceStore()
        query = "kyc rules for retail accounts"
        similar = Turn(turn_id=1, text="kyc rules retail accounts", age_in_turns=0)
        dissimilar = Turn(turn_id=2, text="utterly unrelated topic xyzzy", age_in_turns=0)
        s_sim = score_for_ejection(similar, query, store, led)
        s_dis = score_for_ejection(dissimilar, query, store, led)
        assert s_dis.similarity_term > s_sim.similarity_term


def test_older_turn_has_larger_age_term() -> None:
    with Ledger(":memory:") as led:
        store = EvidenceStore()
        young = Turn(turn_id=0, text="some content", age_in_turns=1)
        old = Turn(turn_id=1, text="some content", age_in_turns=10)
        s_y = score_for_ejection(young, "ref", store, led, age_normaliser=10)
        s_o = score_for_ejection(old, "ref", store, led, age_normaliser=10)
        assert s_o.age_term > s_y.age_term


def test_negative_alpha_raises() -> None:
    with Ledger(":memory:") as led:
        store = EvidenceStore()
        t = Turn(turn_id=0, text="x", age_in_turns=0)
        with pytest.raises(ValueError, match="non-negative"):
            score_for_ejection(t, "y", store, led, alpha=-0.1)


def test_negative_beta_or_gamma_raises() -> None:
    with Ledger(":memory:") as led:
        store = EvidenceStore()
        t = Turn(turn_id=0, text="x", age_in_turns=0)
        with pytest.raises(ValueError, match="non-negative"):
            score_for_ejection(t, "y", store, led, beta=-0.1)
        with pytest.raises(ValueError, match="non-negative"):
            score_for_ejection(t, "y", store, led, gamma=-0.1)


def test_eject_top_k_returns_at_most_k() -> None:
    with Ledger(":memory:") as led:
        store = EvidenceStore()
        turns = [
            Turn(turn_id=i, text=f"content {i}", age_in_turns=i)
            for i in range(5)
        ]
        out = eject_top_k(
            turns,
            "current",
            store,
            led,
            k=2,
            threshold=0.0,
        )
        assert len(out) == 2
        assert all(isinstance(e, EjectedTurn) for e in out)


def test_eject_top_k_threshold_excludes_low_scores() -> None:
    with Ledger(":memory:") as led:
        store = EvidenceStore()
        # All turns identical to query → similarity ~1, similarity_term ~0
        # → likely below a high threshold.
        turns = [
            Turn(turn_id=i, text="same text", age_in_turns=0) for i in range(3)
        ]
        out = eject_top_k(
            turns,
            "same text",
            store,
            led,
            k=3,
            threshold=10.0,  # impossibly high
        )
        assert out == []


def test_eject_top_k_persists_when_session_id_provided() -> None:
    with Ledger(":memory:") as led:
        store = EvidenceStore()
        turns = [
            Turn(turn_id=i, text=f"distinct content {i}", age_in_turns=10 - i)
            for i in range(3)
        ]
        out = eject_top_k(
            turns,
            "different query",
            store,
            led,
            k=2,
            threshold=0.0,
            session_id="sess-1",
            persist=True,
        )
        assert len(out) == 2
        rows = led._conn.execute(  # noqa: SLF001
            "SELECT session_id, ejected_turn_id, ejection_score,"
            " similarity_term, age_term, usefulness_term, threshold_at_eject"
            " FROM context_ejections WHERE session_id='sess-1'"
        ).fetchall()
        assert len(rows) == 2
        for r in rows:
            assert r[0] == "sess-1"


def test_eject_top_k_does_not_persist_when_persist_false() -> None:
    with Ledger(":memory:") as led:
        store = EvidenceStore()
        turns = [Turn(turn_id=0, text="t", age_in_turns=0)]
        eject_top_k(
            turns,
            "q",
            store,
            led,
            k=1,
            threshold=0.0,
            session_id="sim",
            persist=False,
        )
        rows = led._conn.execute(  # noqa: SLF001
            "SELECT id FROM context_ejections"
        ).fetchall()
    assert rows == []


def test_eject_top_k_empty_turns_returns_empty() -> None:
    with Ledger(":memory:") as led:
        store = EvidenceStore()
        out = eject_top_k([], "q", store, led, k=5, threshold=0.0)
        assert out == []


def test_eject_top_k_negative_k_raises() -> None:
    with Ledger(":memory:") as led:
        store = EvidenceStore()
        with pytest.raises(ValueError, match="non-negative"):
            eject_top_k([], "q", store, led, k=-1, threshold=0.0)


def test_eject_top_k_threshold_out_of_range_raises() -> None:
    with Ledger(":memory:") as led:
        store = EvidenceStore()
        with pytest.raises(ValueError, match=r"\[0, 10\]"):
            eject_top_k([], "q", store, led, k=1, threshold=99.0)


def test_score_uses_historical_usefulness_when_neighbours_match() -> None:
    """Adding cec_meta_outcomes for an answer that matches a neighbour's
    answer should pull historical_usefulness toward the recorded
    held_up rate."""
    with Ledger(":memory:") as led:
        store = EvidenceStore()
        store.add("question alpha", "answer-alpha", correct=True)
        # Tag the meta-outcome map with a held_up=0 for that answer.
        led._conn.execute(  # noqa: SLF001
            "INSERT INTO cec_meta_predictions(claim_id, predicted_confidence,"
            " horizon_days) VALUES ('answer-alpha', 0.5, 30)"
        )
        led._conn.execute(  # noqa: SLF001
            "INSERT INTO cec_meta_outcomes(claim_id, held_up)"
            " VALUES ('answer-alpha', 0)"
        )
        led._conn.commit()  # noqa: SLF001
        t = Turn(turn_id=0, text="question alpha", age_in_turns=0)
        s = score_for_ejection(t, "current", store, led)
        # held_up=0 means the matched neighbour was useless → usefulness=0
        # → usefulness_term contribution is 0 (i.e., usefulness_term ~ 0).
        # The default 0.5 prior would give -gamma*0.5 = -0.15.
        assert s.usefulness_term > -0.15  # less negative than the prior


def test_score_falls_back_to_neutral_when_no_text() -> None:
    with Ledger(":memory:") as led:
        store = EvidenceStore()
        t = Turn(turn_id=0, text="", age_in_turns=0)
        s = score_for_ejection(t, "current", store, led)
        # similarity 0 → similarity_term = alpha*1 = 0.5
        assert s.similarity == 0.0
        assert s.similarity_term == pytest.approx(0.5)


def test_age_normaliser_zero_uses_default() -> None:
    with Ledger(":memory:") as led:
        store = EvidenceStore()
        t = Turn(turn_id=0, text="x", age_in_turns=0)
        # age_normaliser of 0 must not divide-by-zero. Treated as None.
        s = score_for_ejection(t, "y", store, led, age_normaliser=0)
        assert 0.0 <= s.age_normalised <= 1.0
