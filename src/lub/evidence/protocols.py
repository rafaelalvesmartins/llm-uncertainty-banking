# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Structural protocols for evidence-store backends.

ADR 0008 commits to shipping :class:`EvidenceStoreProtocol` so a real
vector DB can be swapped in for production. Consumers (CEC, Context
Autopilot, hooks, the swarm) duck-type against this protocol rather
than the concrete :class:`lub.evidence.store.EvidenceStore`.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from lub.evidence.store import Neighbour


@runtime_checkable
class EvidenceStoreProtocol(Protocol):
    """Structural contract for any evidence-store backend."""

    dim: int

    def __len__(self) -> int:
        """Return the number of records currently stored."""
        ...

    def add(
        self,
        question: str,
        answer: str,
        correct: bool,
        uq_scores: dict[str, float] | None = None,
    ) -> None:
        """Insert one labelled example into the store."""
        ...

    def query(self, question: str, k: int = 5) -> list[Neighbour]:
        """Return the top-k neighbours of question by similarity."""
        ...


@runtime_checkable
class PersistentEvidenceStoreProtocol(EvidenceStoreProtocol, Protocol):
    """Optional extension for backends that support disk persistence."""

    def save(self, path: str | Path) -> None:
        """Persist the store to ``path``."""
        ...

    @classmethod
    def load(cls, path: str | Path) -> PersistentEvidenceStoreProtocol:
        """Hydrate a store previously written with :meth:`save`."""
        ...


class InMemoryEvidenceStore:
    """Tiny dict-backed evidence store -- canonical plug-in reference.

    Records are kept as dicts and "similarity" is bag-of-words Jaccard.
    Use for tests and as a concrete example of satisfying the Protocol.
    Not appropriate for production -- the real
    :class:`~lub.evidence.store.EvidenceStore` (TF-IDF + cosine) is
    canonical for >100 records.
    """

    dim: int = 1

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []
        self._drift_events: list[dict[str, Any]] = []

    def __len__(self) -> int:
        return len(self._records)

    @staticmethod
    def _tokens(s: str) -> set[str]:
        return {t.lower() for t in s.split() if t}

    def _similarity(self, a: str, b: str) -> float:
        ta, tb = self._tokens(a), self._tokens(b)
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

    def add(
        self,
        question: str,
        answer: str,
        correct: bool,
        uq_scores: dict[str, float] | None = None,
    ) -> None:
        """Append one labelled example to the in-memory list.

        ``uq_scores`` is copied (not stored by reference) so the caller
        can mutate its dict afterwards without affecting the store.
        """
        self._records.append(
            {
                "question": question,
                "answer": answer,
                "correct": bool(correct),
                "uq_scores": dict(uq_scores or {}),
            }
        )

    def query(self, question: str, k: int = 5) -> list[dict[str, Any]]:
        """Return the top-``k`` records by Jaccard token overlap.

        Linear scan over every stored record — fine for tests, not for
        production. Use the TF-IDF :class:`~lub.evidence.store.EvidenceStore`
        for >100 records.

        Raises:
            ValueError: If ``k <= 0``.
        """
        if k <= 0:
            raise ValueError(f"k must be positive, got {k}")
        scored = [(self._similarity(question, r["question"]), r) for r in self._records]
        scored.sort(key=lambda t: t[0], reverse=True)
        return [r for _, r in scored[:k]]

    def record_drift_event(self, event: dict[str, Any]) -> None:
        """Record a drift event; consumed by lub.challenge.drift_reasoning."""
        self._drift_events.append(dict(event))

    def drift_events(
        self,
        since: datetime | None = None,
    ) -> Iterable[dict[str, Any]]:
        """Return drift events with ``at >= since`` (or all if ``since`` is None).

        Events without an ``at`` field are always included — defensive
        handling for ad-hoc events written by older code paths.
        """
        if since is None:
            return list(self._drift_events)
        return [e for e in self._drift_events if not e.get("at") or e["at"] >= since]

    def close(self) -> None:
        """No-op for the in-memory store; present to satisfy the Protocol."""
        return


__all__ = [
    "EvidenceStoreProtocol",
    "InMemoryEvidenceStore",
    "PersistentEvidenceStoreProtocol",
]
