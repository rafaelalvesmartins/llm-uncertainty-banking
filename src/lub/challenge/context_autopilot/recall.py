# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""lub.challenge.context_autopilot.recall -- recall-risk flagging.

When a *later* turn references content that was previously ejected
(detected via k-NN against the ejection log), Context Autopilot flags
the turn as a *recall risk* and writes a row to ``context_recall_flags``.

The autopilot does NOT silently re-fetch the ejected content. That
would re-introduce content the audit trail logged as ejected, polluting
the calibration signal and making the surface unauditable. Re-injection
is a human/operator decision, made on the strength of this flag.

Spec: planning/25_Context_Autopilot_Spec_2026-04-25.md section 1.3.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

import structlog

_LOG = structlog.get_logger("lub.challenge.context_autopilot.recall")


@dataclass(frozen=True)
class EjectionLogEntry:
    """One row of the per-session ejection log we scan for matches."""

    eject_id: int
    session_id: str
    ejected_turn_id: int
    text: str = ""


@dataclass(frozen=True)
class RecallRiskFlag:
    """One detected recall-risk event.

    Attributes
    ----------
    later_turn_id:
        The turn that re-references previously ejected content.
    referenced_eject_id:
        Foreign-key into ``context_ejections``.
    similarity_score:
        Cosine similarity between *later_turn* and the ejected turn.
    metadata:
        Extra context (k used, threshold used, ...).
    """

    later_turn_id: int
    referenced_eject_id: int
    similarity_score: float
    session_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _embed_query(text: str, evidence_store: Any) -> Any:
    from lub.evidence.store import _embed

    dim = getattr(evidence_store, "dim", 1024)
    return _embed(text, dim)


def detect_recall_risk(
    later_turn: Any,
    ejection_log: list[EjectionLogEntry],
    evidence_store: Any,
    *,
    k: int | None = None,
    similarity_threshold: float | None = None,
    ledger: Any = None,
    persist: bool = True,
) -> RecallRiskFlag | None:
    """Detect whether *later_turn* re-references any ejected content.

    Parameters
    ----------
    later_turn:
        Either a string (the turn text) or any object with ``.text``
        and ``.turn_id`` attributes.
    ejection_log:
        Past ejection records to scan. Each entry's ``text`` is
        embedded and compared against ``later_turn``.
    evidence_store:
        :class:`lub.evidence.EvidenceStore` -- only used for its
        ``dim`` attribute and the deterministic hash embedder.
    k:
        Number of top neighbours considered. The single most-similar
        ejection above ``similarity_threshold`` is returned.
    similarity_threshold:
        Minimum cosine similarity for the flag to fire. Default 0.3
        is intentionally conservative; tune up to reduce false alarms.
    ledger:
        If provided AND ``persist=True``, the flag is written to
        ``context_recall_flags``.
    persist:
        Set to ``False`` for read-only / simulation paths.

    Returns
    -------
    RecallRiskFlag | None
        A flag if a strong match was found, else ``None``.
    """
    # Defaults centralized in lub.challenge.defaults (Pattern 1.6).
    from lub.challenge.defaults import (
        RECALL_K_NEIGHBOURS,
        RECALL_SIMILARITY_THRESHOLD,
    )

    if k is None:
        k = RECALL_K_NEIGHBOURS
    if similarity_threshold is None:
        similarity_threshold = RECALL_SIMILARITY_THRESHOLD
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")
    if not 0.0 <= similarity_threshold <= 1.0:
        raise ValueError(f"similarity_threshold must be in [0, 1], got {similarity_threshold}")

    later_text: str
    later_turn_id: int
    if isinstance(later_turn, str):
        later_text = later_turn
        later_turn_id = -1
    else:
        later_text = str(getattr(later_turn, "text", ""))
        later_turn_id = int(getattr(later_turn, "turn_id", -1))

    if not later_text or not ejection_log:
        return None

    later_vec = _embed_query(later_text, evidence_store)

    scored: list[tuple[float, EjectionLogEntry]] = []
    for entry in ejection_log:
        if not entry.text:
            continue
        ev = _embed_query(entry.text, evidence_store)
        sim = float((later_vec * ev).sum())
        scored.append((sim, entry))

    if not scored:
        return None

    scored.sort(key=lambda p: p[0], reverse=True)
    top = scored[:k]
    best_sim, best_entry = top[0]

    if best_sim < similarity_threshold:
        return None

    flag = RecallRiskFlag(
        later_turn_id=int(later_turn_id),
        referenced_eject_id=int(best_entry.eject_id),
        similarity_score=float(best_sim),
        session_id=str(best_entry.session_id),
        metadata={
            "k": int(k),
            "similarity_threshold": float(similarity_threshold),
            "n_candidates": len(ejection_log),
        },
    )

    if persist and ledger is not None:
        _persist_flag(ledger, flag)

    _LOG.info(
        "context_autopilot.recall_flag",
        later_turn_id=int(later_turn_id),
        referenced_eject_id=int(best_entry.eject_id),
        similarity_score=float(best_sim),
        session_id=str(best_entry.session_id),
        persist=bool(persist),
    )

    return flag


def _persist_flag(ledger: Any, flag: RecallRiskFlag) -> None:
    conn = ledger._conn  # noqa: SLF001
    if not isinstance(conn, sqlite3.Connection):  # pragma: no cover -- defensive
        return
    conn.execute(
        "INSERT INTO context_recall_flags"
        " (session_id, later_turn_id, referenced_eject_id,"
        "  similarity_score, flagged_at)"
        " VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
        (
            flag.session_id,
            int(flag.later_turn_id),
            int(flag.referenced_eject_id),
            float(flag.similarity_score),
        ),
    )
    conn.commit()


def load_ejection_log(ledger: Any, session_id: str) -> list[EjectionLogEntry]:
    """Read the ejection log for *session_id* from the ledger.

    The log only contains the structural rows -- the original *text*
    of the ejected turn is the caller's responsibility to attach
    (we don't store full prompt text in ``context_ejections``).
    """
    conn = ledger._conn  # noqa: SLF001
    rows = conn.execute(
        "SELECT id, session_id, ejected_turn_id"
        " FROM context_ejections WHERE session_id = ?"
        " ORDER BY id ASC",
        (str(session_id),),
    ).fetchall()
    return [
        EjectionLogEntry(
            eject_id=int(r[0]),
            session_id=str(r[1]),
            ejected_turn_id=int(r[2]),
            text="",
        )
        for r in rows
    ]


__all__ = [
    "EjectionLogEntry",
    "RecallRiskFlag",
    "detect_recall_risk",
    "load_ejection_log",
]
