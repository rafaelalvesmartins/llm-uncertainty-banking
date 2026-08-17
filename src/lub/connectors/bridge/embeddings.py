# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Shared text embedding utilities for the Bridge platform.

Both :mod:`lub.connectors.bridge.memory` (semantic cache) and
:mod:`lub.connectors.bridge.rag` (retrieval) need cheap, deterministic
text embeddings. Before this module they each re-implemented the same
hashing-trick pipeline; that duplication is now centralized here so
both modules share one tested, audited code path.

Why hashing-trick (not transformers):

* Pure-python, no model load, no GPU, no API key — runs anywhere LUB runs.
* Deterministic output (BLAKE2 hash → consistent dim assignment) — same
  query always produces the same vector across processes, runs, hosts.
* ~1us per token. Fast enough that semantic search is dominated by the
  cosine loop, not the embedding step.

The trade-off is quality: hashing-trick is a poor man's vectorizer.
For corpora >10k docs or queries needing genuine semantic similarity
(synonyms, paraphrases), swap in a sentence-transformers backend
behind the same API: build a class with ``embed(text) -> tuple[float, ...]``
and ``EMBEDDING_DIM`` and the rest of Bridge keeps working.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Final

__all__ = [
    "EMBEDDING_DIM",
    "cosine",
    "embed",
    "tokenize",
]

# Hashing-trick embedding dimension. 256 keeps cosine separation > 0.05
# for ~10k entries; bigger means less collision but more memory per entry.
EMBEDDING_DIM: Final = 256

# Tokens are alphanumeric runs of length >= 2.
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


def tokenize(text: str) -> list[str]:
    """Lowercase + alphanumeric token split. Drops 1-char tokens."""
    return _TOKEN_RE.findall(text.lower())


def embed(
    tokens: list[str],
    idf: dict[str, float] | None = None,
) -> tuple[float, ...]:
    """Hashing-trick TF (or TF-IDF if idf table provided) embedding.

    Each token contributes ``log(1 + count)`` (or ``count * idf[tok]``)
    at a hash-determined dimension; sign comes from a second hash bit.
    Output is L2-normalized so cosine similarity == dot product.
    """
    if not tokens:
        return tuple([0.0] * EMBEDDING_DIM)

    weights: dict[int, float] = {}
    for tok in tokens:
        h = hashlib.blake2s(tok.encode("utf-8"), digest_size=4).digest()
        idx = int.from_bytes(h[:2], "little") % EMBEDDING_DIM
        sign = 1.0 if (h[2] & 1) else -1.0
        w = idf.get(tok, 1.0) if idf else 1.0
        weights[idx] = weights.get(idx, 0.0) + sign * w

    vec = [0.0] * EMBEDDING_DIM
    for idx, raw in weights.items():
        vec[idx] = math.copysign(math.log1p(abs(raw)), raw)

    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return tuple(vec)


def cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Cosine similarity of two L2-normalized vectors. Equivalent to dot product."""
    return sum(x * y for x, y in zip(a, b, strict=False))
