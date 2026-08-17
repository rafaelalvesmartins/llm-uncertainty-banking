# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""In-memory k-NN evidence store over hashed TF-IDF vectors.

Deliberately minimal: numpy + stdlib only. Swap in a real vector DB
when the corpus exceeds a few hundred thousand entries.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from lub.types import UncertaintyResult

_TOKEN_RE = re.compile(r"[\w'-]+", re.UNICODE)
_DEFAULT_DIM = 1024


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _hash_token(token: str, dim: int) -> int:
    h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(h, "little") % dim


def _embed(text: str, dim: int = _DEFAULT_DIM) -> npt.NDArray[np.float32]:
    """Hashed TF vector with L2 normalisation.

    Fast, deterministic, no training. Good enough for k-NN over a few
    thousand banking questions.
    """
    vec = np.zeros(dim, dtype=np.float32)
    for tok in _tokenize(text):
        vec[_hash_token(tok, dim)] += 1.0
    norm = float(np.linalg.norm(vec))
    if norm > 0.0:
        vec /= norm
    return vec


@dataclass(frozen=True)
class Neighbour:
    """One k-NN hit with its historical correctness."""

    question: str
    answer: str
    correct: bool
    cosine_similarity: float
    uq_scores: dict[str, float] = field(default_factory=dict)


@dataclass
class _Record:
    question: str
    answer: str
    correct: bool
    uq_scores: dict[str, float]
    vector: npt.NDArray[np.float32]


class EvidenceStore:
    """In-memory k-NN evidence store with on-disk persistence.

    Parameters
    ----------
    dim:
        Vector dimensionality for the hashed TF embedding. Higher is
        less collision-prone but slower. 1024 is a good default.
    """

    def __init__(self, dim: int = _DEFAULT_DIM) -> None:
        self.dim = int(dim)
        self._records: list[_Record] = []

    def __len__(self) -> int:
        return len(self._records)

    def add(
        self,
        question: str,
        answer: str,
        correct: bool,
        uq_scores: dict[str, float] | None = None,
    ) -> None:
        """Insert one labelled example into the store."""
        self._records.append(
            _Record(
                question=question,
                answer=answer,
                correct=bool(correct),
                uq_scores=dict(uq_scores or {}),
                vector=_embed(question, self.dim),
            )
        )

    def query(self, question: str, k: int = 5) -> list[Neighbour]:
        """Return the top-*k* neighbours of *question* by cosine similarity."""
        if k <= 0:
            raise ValueError(f"k must be positive, got {k}")
        if not self._records:
            return []
        q = _embed(question, self.dim)
        # Records already L2-normalised → inner product == cosine.
        sims = np.stack([r.vector for r in self._records]) @ q
        top_idx = np.argsort(-sims)[:k]
        out: list[Neighbour] = []
        for i in top_idx:
            r = self._records[int(i)]
            out.append(
                Neighbour(
                    question=r.question,
                    answer=r.answer,
                    correct=r.correct,
                    cosine_similarity=float(sims[int(i)]),
                    uq_scores=dict(r.uq_scores),
                )
            )
        return out

    def save(self, path: str | Path) -> None:
        """Persist the store as a single ``.npz`` archive."""
        p = Path(path)
        np.savez(
            p,
            vectors=np.stack([r.vector for r in self._records])
            if self._records
            else np.zeros((0, self.dim), dtype=np.float32),
            questions=np.array([r.question for r in self._records], dtype=object),
            answers=np.array([r.answer for r in self._records], dtype=object),
            correct=np.array([int(r.correct) for r in self._records], dtype=np.int8),
            dim=np.int64(self.dim),
        )

    @classmethod
    def load(cls, path: str | Path) -> EvidenceStore:
        """Hydrate a store previously written with :meth:`save`."""
        data = np.load(path, allow_pickle=True)
        store = cls(dim=int(data["dim"]))
        questions = list(data["questions"])
        answers = list(data["answers"])
        correct = list(data["correct"])
        vectors = data["vectors"]
        for i, q in enumerate(questions):
            store._records.append(  # noqa: SLF001 — class-private access by design.
                _Record(
                    question=str(q),
                    answer=str(answers[i]),
                    correct=bool(correct[i]),
                    uq_scores={},
                    vector=vectors[i].astype(np.float32),
                )
            )
        return store


def retrieval_adjusted(
    result: UncertaintyResult,
    neighbours: list[Neighbour],
    weight: float = 0.3,
) -> UncertaintyResult:
    """Blend *result*'s confidence toward the neighbour-correctness rate.

    ``new_confidence = (1 - weight) * old_confidence + weight * correct_rate``.

    ``weight == 0`` is a passthrough, ``weight == 1`` hands the decision
    fully to retrieval. Keep it low (0.1–0.3) unless the store is
    trusted and large.
    """
    if not 0.0 <= weight <= 1.0:
        raise ValueError(f"weight must be in [0, 1], got {weight}")
    if not neighbours:
        return result
    correct_rate = sum(1.0 for n in neighbours if n.correct) / len(neighbours)
    new_conf = (1.0 - weight) * float(result.confidence) + weight * correct_rate
    new_conf = max(0.0, min(1.0, new_conf))
    raw_scores: dict[str, Any] = dict(result.raw_scores)
    raw_scores["retrieval_correct_rate"] = correct_rate
    raw_scores["retrieval_weight"] = weight
    return dataclasses.replace(
        result,
        confidence=new_conf,
        raw_scores={k: float(v) for k, v in raw_scores.items() if isinstance(v, (int, float))},
    )


def _cosine(a: npt.NDArray[Any], b: npt.NDArray[Any]) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# Suppress warning about unused helper — kept for debugging.
assert math and callable(_cosine)  # noqa: S101


__all__ = ["EvidenceStore", "Neighbour", "retrieval_adjusted"]
