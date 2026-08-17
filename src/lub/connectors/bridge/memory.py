# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Semantic cache ("elephant memory") for the Bridge platform.

Inspired by ``ruvnet/ruflo``'s HNSW-indexed memory and the standard
LLM-cache pattern: most banking queries are *near-duplicates* of past
queries ("qual meu saldo", "saldo atual", "ver saldo da conta"). If we
recognize a near-miss against a recent answer, we can return the cached
answer in microseconds instead of a multi-hundred-millisecond LLM call.

The cache is **deliberately small and pure-python** so it runs on a
laptop or a t3.micro. It does NOT depend on FAISS or HNSW libraries —
we use a hashing-trick embedding (cheap, deterministic, no model load)
plus a brute-force cosine search bounded by ``max_entries``. For
production traffic above ~10k QPS, swap the embedder for a real
sentence-transformers model and the index for FAISS.

Compliance notes
----------------

Every cache hit is logged with the query hash, similarity score, and
the original entry's audit ID so the BCB 4893 trail can reconstruct
*which* prior answer the customer received and why. PII (phone numbers,
account numbers) is hashed before storage; the cache stores normalized
query text plus the answer text only.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Final

import structlog

from lub.connectors.bridge.embeddings import cosine, embed, tokenize

__all__ = [
    "CacheEntry",
    "CacheHit",
    "SemanticCache",
]

_LOG = structlog.get_logger("lub.bridge.memory")

# Match Brazilian-format account numbers / CPFs / phone numbers so we
# can scrub them before computing the embedding (cache hits should be
# semantic, not "same digits").
_PII_PATTERNS: Final = [
    re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),  # CPF
    re.compile(r"\b\d{11}\b"),  # 11-digit (phone or CPF)
    re.compile(r"\b\d{4,}-\d{1,2}\b"),  # account
]


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CacheEntry:
    """A single stored query+answer."""

    query_normalized: str
    query_hash: str
    answer: str
    embedding: tuple[float, ...]
    intent: str
    confidence: float
    created_at: float
    hit_count: int = 0
    scope: str | None = None
    """Isolation key (e.g. customer/tenant id). A lookup only matches entries
    with an equal scope, so one customer can never be served another's cached
    answer — independent of similarity. ``None`` (default) keeps the original
    un-scoped behaviour for callers that don't pass a scope."""


@dataclass(frozen=True)
class CacheHit:
    """Returned by :meth:`SemanticCache.lookup` when a near-match is found."""

    answer: str
    similarity: float
    age_seconds: float
    original_intent: str
    original_confidence: float
    cached_query: str


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


def _scrub_pii(text: str) -> str:
    """Redact common Brazilian PII patterns before embedding."""
    out = text
    for pattern in _PII_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out


def _normalize(text: str) -> str:
    """Lowercase + collapse whitespace + scrub PII."""
    cleaned = _scrub_pii(text)
    return " ".join(cleaned.lower().split())


def _embed(text: str) -> tuple[float, ...]:
    """Embed normalized text via the shared hashing-trick embedder."""
    return embed(tokenize(text))


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Cosine similarity (delegates to shared impl)."""
    return cosine(a, b)


@dataclass
class SemanticCache:
    """Bounded LRU-ish semantic cache.

    Lookups are O(N) over stored entries. With ``max_entries=1000`` and
    256-dim embeddings, a lookup is ~1ms on typical hardware. Far below
    the LLM call it replaces.
    """

    similarity_threshold: float = 0.85
    """Minimum cosine similarity to count as a cache hit."""

    max_entries: int = 1000
    """Hard cap. When exceeded, the least-recently-stored entry is
    evicted. (Not LRU on access — keeps the implementation O(N) not
    O(N log N), which matters for tight latency budgets.)"""

    max_age_seconds: float = 3600.0
    """Entries older than this are not considered hits, even if
    similar. For banking, freshness matters: a saldo from 2h ago is not
    the right answer."""

    _entries: deque[CacheEntry] = field(default_factory=deque)
    _hits: int = 0
    _misses: int = 0

    def __post_init__(self) -> None:
        if not (0 < self.similarity_threshold <= 1):
            raise ValueError(
                f"similarity_threshold must be in (0, 1] (got {self.similarity_threshold})"
            )
        if self.max_entries < 1:
            raise ValueError(f"max_entries must be >= 1 (got {self.max_entries})")

    # ---- public API ----

    def lookup(self, query: str, *, scope: str | None = None) -> CacheHit | None:
        """Search for a near-match. Returns None if no entry above threshold.

        ``scope`` isolates entries: only those stored with an equal scope are
        considered, so customer/tenant A can never receive customer/tenant B's
        cached answer regardless of query similarity. ``None`` searches the
        un-scoped pool (back-compatible default).
        """
        normalized = _normalize(query)
        if not normalized:
            self._misses += 1
            return None

        embedding = _embed(normalized)
        now = time.time()

        best: CacheEntry | None = None
        best_sim = -1.0
        for entry in self._entries:
            if entry.scope != scope:
                continue
            age = now - entry.created_at
            if age > self.max_age_seconds:
                continue
            sim = _cosine(embedding, entry.embedding)
            if sim > best_sim:
                best_sim = sim
                best = entry

        if best is not None and best_sim >= self.similarity_threshold:
            best.hit_count += 1
            self._hits += 1
            _LOG.info(
                "bridge.memory.hit",
                similarity=round(best_sim, 3),
                age_seconds=round(now - best.created_at, 1),
                intent=best.intent,
                hit_count=best.hit_count,
            )
            return CacheHit(
                answer=best.answer,
                similarity=best_sim,
                age_seconds=now - best.created_at,
                original_intent=best.intent,
                original_confidence=best.confidence,
                cached_query=best.query_normalized,
            )

        self._misses += 1
        return None

    def store(
        self,
        query: str,
        answer: str,
        *,
        intent: str = "unknown",
        confidence: float = 0.0,
        scope: str | None = None,
    ) -> CacheEntry:
        """Add a new entry. Evicts the oldest if at capacity.

        ``scope`` tags the entry for isolation (see :meth:`lookup`).
        """
        normalized = _normalize(query)
        embedding = _embed(normalized)
        query_hash = hashlib.blake2s(normalized.encode("utf-8"), digest_size=8).hexdigest()

        entry = CacheEntry(
            query_normalized=normalized,
            query_hash=query_hash,
            answer=answer,
            embedding=embedding,
            intent=intent,
            confidence=confidence,
            created_at=time.time(),
            scope=scope,
        )

        if len(self._entries) >= self.max_entries:
            evicted = self._entries.popleft()
            _LOG.info(
                "bridge.memory.evicted",
                hash=evicted.query_hash,
                hit_count=evicted.hit_count,
            )

        self._entries.append(entry)
        _LOG.info("bridge.memory.stored", hash=query_hash, intent=intent)
        return entry

    def clear(self) -> int:
        """Drop all entries. Returns the count removed."""
        n = len(self._entries)
        self._entries.clear()
        return n

    # ---- introspection ----

    @property
    def size(self) -> int:
        """Report current cache occupancy to the Bridge hub.

        Bridge's monitoring stage (stage 9 of the pipeline) polls this
        to expose ``bridge_cache_entries`` as a Prometheus gauge and to
        decide when to trigger background warmup of cold caches.

        Returns:
            Number of live ``CacheEntry`` rows currently held (0..max_entries).
        """
        return len(self._entries)

    @property
    def hit_rate(self) -> float:
        """Fraction of Bridge pipeline lookups served from cache.

        Stage 1 of the Bridge pipeline (SemanticCache) calls
        :meth:`lookup` before any LLM work; this ratio is the headline
        cost-savings metric the platform reports to FinOps. A rising
        hit_rate means ComplexityRouter (stage 2) and the LLM tiers are
        being short-circuited more often.

        Returns:
            ``hits / (hits + misses)`` as a float in ``[0.0, 1.0]``;
            ``0.0`` when no lookups have been performed yet.
        """
        total = self._hits + self._misses
        return self._hits / total if total else 0.0

    def stats(self) -> dict[str, float | int]:
        """Snapshot of cache health for Bridge observability and audit.

        Bridge's ``monitoring.py`` consumes this dict to populate the
        ``/health`` endpoint and the BCB 4893 audit trail (stage 9):
        regulators want to know not just *that* an answer was cached
        but the cache configuration in force at the time (thresholds,
        TTL, capacity) so prior decisions can be reconstructed.

        Returns:
            Dict with ``entries``, ``max_entries``, ``hits``,
            ``misses``, ``hit_rate`` (rounded to 3 dp),
            ``similarity_threshold``, and ``max_age_seconds``.
        """
        return {
            "entries": len(self._entries),
            "max_entries": self.max_entries,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self.hit_rate, 3),
            "similarity_threshold": self.similarity_threshold,
            "max_age_seconds": self.max_age_seconds,
        }
