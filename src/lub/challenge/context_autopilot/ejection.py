# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""lub.challenge.context_autopilot.ejection -- calibrated context ejection.

When the headroom ratio falls below threshold, Context Autopilot
computes a per-turn ejection score:

::

    score(turn_i) = alpha * (1 - similarity(turn_i, current_query))
                  + beta  * age_in_turns(turn_i)
                  - gamma * historical_usefulness(turn_i)

* ``similarity`` -- cosine similarity from
  :class:`lub.evidence.EvidenceStore`.
* ``age_in_turns`` -- normalised positional age (0.0 = current,
  1.0 = oldest in the supplied window).
* ``historical_usefulness`` -- in [0, 1]. Looks up turns that were
  k-NN-similar to ``turn`` in the ``cec_meta_outcomes`` history; the
  fraction whose claim ``held_up`` is the usefulness signal. Defaults
  to 0.5 when no history matches.

Top-k highest-score turns above ``threshold`` are marked ejected. The
ejection record is persisted to ``context_ejections`` so the recall-flag
module can detect later turns that re-reference ejected content.

Spec: planning/25_Context_Autopilot_Spec_2026-04-25.md section 1.2.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

import structlog

_LOG = structlog.get_logger("lub.challenge.context_autopilot.ejection")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Turn:
    """One conversational turn in the active context window.

    The minimal feature set needed to score a turn for ejection.
    """

    turn_id: int
    text: str
    age_in_turns: int = 0


@dataclass(frozen=True)
class EjectionScore:
    """Decomposed ejection score for one turn.

    The three additive terms (after weighting) sum to ``score``. They
    are kept separate so the report and the audit log can show *why*
    a turn was ejected, not just that it was.
    """

    turn_id: int
    score: float
    similarity_term: float
    age_term: float
    usefulness_term: float
    similarity: float
    age_normalised: float
    historical_usefulness: float
    alpha: float
    beta: float
    gamma: float


@dataclass(frozen=True)
class EjectedTurn:
    """One turn marked for ejection, plus its decomposition."""

    turn_id: int
    score: EjectionScore
    threshold: float
    text_snippet: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _similarity(turn_text: str, current_query: str, evidence_store: Any) -> float:
    """Cosine similarity between *turn_text* and *current_query*.

    Uses the embedding shipped with :class:`lub.evidence.EvidenceStore`.
    Falls back to 0.0 when the store cannot embed (e.g., empty text).
    """
    # Re-use the private embedder so we don't have to round-trip through
    # ``EvidenceStore.add`` + ``query``.
    try:
        from lub.evidence.store import _embed
    except Exception as exc:  # pragma: no cover -- defensive
        _LOG.debug(
            "ejection.similarity.embed_unavailable",
            reason="failed to import lub.evidence.store._embed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return 0.0

    dim = getattr(evidence_store, "dim", 1024)
    if not turn_text or not current_query:
        return 0.0
    a = _embed(turn_text, dim)
    b = _embed(current_query, dim)
    # Vectors are L2-normalised so dot == cosine.
    return float((a * b).sum())


def _historical_usefulness(
    turn_text: str,
    evidence_store: Any,
    ledger: Any,
    k: int = 5,
) -> float:
    """Estimate how useful similar past turns proved to be.

    We use ``EvidenceStore.query()`` to retrieve k neighbours of the
    turn and join their ``cec_meta_outcomes.held_up`` flags via the
    answer text (treated as the claim_id if recorded). The returned
    value is the *held-up rate* of matching neighbours.

    When no matches are found (cold start), returns 0.5 -- a maximally
    uninformative prior so neither the high nor the low end of the
    score distribution gets a free lift.
    """
    if not turn_text:
        return 0.5

    try:
        neighbours = evidence_store.query(turn_text, k=k)
    except Exception as exc:
        _LOG.debug(
            "ejection.usefulness.query_failed",
            reason="evidence_store.query raised; falling back to uninformative prior",
            error_type=type(exc).__name__,
            error=str(exc),
            k=k,
        )
        return 0.5

    if not neighbours:
        return 0.5

    # Pull all known cec_meta_outcomes from the ledger as a map
    # claim_id -> held_up. The schema guarantees this column exists in
    # v2+.
    conn = getattr(ledger, "_conn", None)
    held_map: dict[str, int] = {}
    if isinstance(conn, sqlite3.Connection):
        try:
            rows = conn.execute("SELECT claim_id, held_up FROM cec_meta_outcomes").fetchall()
            for r in rows:
                held_map[str(r[0])] = int(r[1])
        except sqlite3.Error:
            held_map = {}

    matches: list[int] = []
    for n in neighbours:
        # Join by either the answer string or the question hash; both
        # are common ways CEC tagged claim_ids in the meta tables.
        for key in (
            getattr(n, "answer", ""),
            getattr(n, "question", ""),
        ):
            if key and key in held_map:
                matches.append(held_map[key])
                break
        else:
            # Fall back to the neighbour's own correctness flag if the
            # ledger didn't record a meta-outcome for it.
            if getattr(n, "correct", None) is not None:
                matches.append(int(bool(n.correct)))

    if not matches:
        return 0.5
    return float(sum(matches)) / float(len(matches))


def _normalise_age(age: int, ages: list[int]) -> float:
    """Normalise *age* into [0, 1] given the population of ages."""
    if not ages:
        return 0.0
    max_age = max(ages)
    if max_age <= 0:
        return 0.0
    return min(1.0, max(0.0, age / float(max_age)))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_for_ejection(
    turn: Turn,
    current_query: str,
    evidence_store: Any,
    ledger: Any,
    *,
    alpha: float | None = None,
    beta: float | None = None,
    gamma: float | None = None,
    age_normaliser: float | None = None,
    k: int = 5,
) -> EjectionScore:
    """Compute the calibrated ejection score for one turn.

    Parameters
    ----------
    turn:
        The :class:`Turn` to score.
    current_query:
        The model's current input -- the "near future" against which
        ``turn`` is being compared.
    evidence_store:
        :class:`lub.evidence.EvidenceStore` providing embeddings + k-NN.
    ledger:
        :class:`lub.ledger.Ledger` -- read-only here; we look up
        historical ``cec_meta_outcomes`` rows.
    alpha, beta, gamma:
        Weights for the three score terms. Defaults: 0.5 / 0.2 / 0.3.
    age_normaliser:
        Optional fixed denominator for age normalisation. When ``None``
        the caller can post-normalise; otherwise we divide by this.
    k:
        Number of neighbours to use for historical usefulness. Default 5.
    """
    # Defaults centralized in lub.challenge.defaults (Pattern 1.6).
    from lub.challenge.defaults import (
        EJECTION_ALPHA,
        EJECTION_BETA,
        EJECTION_GAMMA,
    )

    if alpha is None:
        alpha = EJECTION_ALPHA
    if beta is None:
        beta = EJECTION_BETA
    if gamma is None:
        gamma = EJECTION_GAMMA
    if alpha < 0 or beta < 0 or gamma < 0:
        raise ValueError(f"alpha/beta/gamma must be non-negative, got {alpha=}, {beta=}, {gamma=}")
    sim = _similarity(turn.text, current_query, evidence_store)
    if age_normaliser is not None and age_normaliser > 0:
        age_norm = min(1.0, max(0.0, turn.age_in_turns / float(age_normaliser)))
    else:
        # Without a population, the raw age is clamped against a
        # reasonable default of 100 turns so a single-turn caller
        # doesn't get a divide-by-zero.
        age_norm = min(1.0, max(0.0, turn.age_in_turns / 100.0))
    usefulness = _historical_usefulness(turn.text, evidence_store, ledger, k=k)

    similarity_term = float(alpha) * (1.0 - sim)
    age_term = float(beta) * age_norm
    usefulness_term = -float(gamma) * usefulness
    score = similarity_term + age_term + usefulness_term

    return EjectionScore(
        turn_id=int(turn.turn_id),
        score=float(score),
        similarity_term=float(similarity_term),
        age_term=float(age_term),
        usefulness_term=float(usefulness_term),
        similarity=float(sim),
        age_normalised=float(age_norm),
        historical_usefulness=float(usefulness),
        alpha=float(alpha),
        beta=float(beta),
        gamma=float(gamma),
    )


def eject_top_k(
    turns: list[Turn],
    current_query: str,
    evidence_store: Any,
    ledger: Any,
    *,
    k: int,
    threshold: float,
    alpha: float = 0.5,
    beta: float = 0.2,
    gamma: float = 0.3,
    session_id: str | None = None,
    persist: bool = True,
) -> list[EjectedTurn]:
    """Score every turn and return the top-*k* above *threshold*.

    Parameters
    ----------
    turns:
        Active context window turns.
    current_query:
        Current input prompt -- the comparison reference.
    evidence_store, ledger:
        Same semantics as :func:`score_for_ejection`.
    k:
        Maximum number of turns to eject.
    threshold:
        Minimum score required for ejection. Turns with ``score <
        threshold`` are kept regardless of rank.
    alpha, beta, gamma:
        Score weights; passed through.
    session_id:
        If provided AND ``persist=True``, ejection rows are written to
        the ``context_ejections`` ledger table.
    persist:
        Set to ``False`` for the simulate-counterfactual codepath
        (read-only "what if" analysis).
    """
    if k < 0:
        raise ValueError(f"k must be non-negative, got {k}")
    if not 0.0 <= threshold <= 10.0:
        raise ValueError(
            f"threshold must be in [0, 10], got {threshold} "
            "(scores are typically in [-gamma, alpha+beta])"
        )

    if not turns:
        return []

    ages = [t.age_in_turns for t in turns]
    age_normaliser = max(ages) if ages else None

    scored: list[EjectionScore] = []
    for t in turns:
        scored.append(
            score_for_ejection(
                t,
                current_query,
                evidence_store,
                ledger,
                alpha=alpha,
                beta=beta,
                gamma=gamma,
                age_normaliser=age_normaliser,
            )
        )

    # Highest score first.
    scored.sort(key=lambda s: s.score, reverse=True)
    over_threshold = [s for s in scored if s.score >= threshold]
    chosen = over_threshold[:k]

    text_by_id = {t.turn_id: t.text for t in turns}

    ejected: list[EjectedTurn] = []
    for s in chosen:
        snippet = text_by_id.get(s.turn_id, "")
        if len(snippet) > 200:
            snippet = snippet[:197] + "..."
        ejected.append(
            EjectedTurn(
                turn_id=s.turn_id,
                score=s,
                threshold=float(threshold),
                text_snippet=snippet,
                metadata={"k": int(k), "n_candidates": len(turns)},
            )
        )

    if persist and session_id is not None and ejected:
        _persist_ejections(ledger, session_id, ejected)

    _LOG.info(
        "context_autopilot.ejected",
        session_id=session_id,
        n_turns=len(turns),
        n_ejected=len(ejected),
        k=int(k),
        threshold=float(threshold),
        persist=bool(persist),
    )

    return ejected


def _persist_ejections(ledger: Any, session_id: str, ejected: list[EjectedTurn]) -> None:
    conn = ledger._conn  # noqa: SLF001
    for e in ejected:
        conn.execute(
            "INSERT INTO context_ejections"
            " (session_id, ejected_turn_id, ejection_score,"
            "  similarity_term, age_term, usefulness_term,"
            "  threshold_at_eject, ejected_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?,"
            "  strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            (
                str(session_id),
                int(e.turn_id),
                float(e.score.score),
                float(e.score.similarity_term),
                float(e.score.age_term),
                float(e.score.usefulness_term),
                float(e.threshold),
            ),
        )
    conn.commit()


__all__ = [
    "Turn",
    "EjectionScore",
    "EjectedTurn",
    "score_for_ejection",
    "eject_top_k",
]
