"""Redis-backed semantic cache adapter for Track D (scale).

FLAG-GATED AND ADDITIVE — nothing here is wired into the running demo.
This module mirrors the ``SemanticCache`` interface defined in
``lub.connectors.bridge.memory`` so it can be swapped in later behind a
feature flag (see docs/SCALE_WIRING.md) without touching any application
code.

Key design decisions
--------------------
* Match strategy: NORMALIZED-KEY exact match (same as the demo cache's
  degenerate-similarity-=1.0 case).  The demo uses cosine similarity with
  a threshold; at Redis scale we trade fuzzy recall for sub-millisecond
  latency.  Callers that need fuzzy matching should stay on the in-process
  ``SemanticCache`` or add a vector index later.
* Scope isolation: the Redis key includes the scope so one customer/tenant
  can NEVER be served another's cached answer, even for identical queries.
  This is the R1 guarantee.
* TTL: set from ``max_age_seconds`` on every write via Redis SETEX.
* Lazy connection: ``redis.from_url(os.environ["REDIS_URL"])`` is called
  only on first use (class-level singleton per URL).
* ``get_cache(fallback)`` factory: returns ``RedisSemanticCache()`` when
  ``REDIS_URL`` is set, otherwise returns ``fallback`` unchanged.  This is
  the single wiring point; the app will call it later.

Needs validation
----------------
* Run ``pytest bridge-ui/backend/scale/test_cache_redis.py`` with a real
  Redis instance to verify TTL expiry timing, connection-error behaviour,
  and JSON serialisation round-trips under load.
* The ``fakeredis`` tests below cover correctness but not network failure
  modes or Redis cluster routing.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# CacheHit — reuse the upstream type when the package is importable, else
# define a structurally compatible dataclass.
# ---------------------------------------------------------------------------

try:
    from lub.connectors.bridge.memory import CacheHit  # type: ignore[import]
except ImportError:  # package not installed in the scale layer's venv
    @dataclass(frozen=True)
    class CacheHit:  # type: ignore[no-redef]
        """Drop-in replica of ``lub.connectors.bridge.memory.CacheHit``."""

        answer: str
        similarity: float
        age_seconds: float
        original_intent: str
        original_confidence: float
        cached_query: str


# ---------------------------------------------------------------------------
# PII scrubbing + normalisation (mirrors memory.py exactly)
# ---------------------------------------------------------------------------

_PII_PATTERNS = [
    re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),  # CPF
    re.compile(r"\b\d{11}\b"),                        # 11-digit phone/CPF
    re.compile(r"\b\d{4,}-\d{1,2}\b"),               # account number
]


def _scrub_pii(text: str) -> str:
    out = text
    for pattern in _PII_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out


def _normalize(text: str) -> str:
    """Lowercase + collapse whitespace + scrub PII (mirrors memory._normalize)."""
    return " ".join(_scrub_pii(text).lower().split())


# ---------------------------------------------------------------------------
# Redis key helpers
# ---------------------------------------------------------------------------

_KEY_PREFIX = "bridge:cache"


def _redis_key(scope: str | None, normalized_query: str) -> str:
    """Build a Redis key that encodes both scope and query.

    Format: ``bridge:cache:<scope>:<normalized_query>``. When scope is ``None``
    a control-character sentinel marks the un-scoped pool — chosen so it cannot
    collide with any real scope/tenant id (which never contains a NUL byte).
    """
    scope_part = scope if scope is not None else "\x00noscope\x00"
    return f"{_KEY_PREFIX}:{scope_part}:{normalized_query}"


# ---------------------------------------------------------------------------
# RedisSemanticCache
# ---------------------------------------------------------------------------


class RedisSemanticCache:
    """Redis-backed cache with the same ``lookup`` / ``store`` signatures as
    ``SemanticCache``.

    Parameters
    ----------
    similarity_threshold:
        Kept for interface parity; not used for matching (exact-key only).
    max_entries:
        Kept for interface parity; Redis enforces capacity via TTL, not
        count.
    max_age_seconds:
        TTL for every stored entry (seconds).  Passed to Redis as integer
        seconds (ceil).
    """

    def __init__(
        self,
        similarity_threshold: float = 0.85,
        max_entries: int = 1000,
        max_age_seconds: float = 3600.0,
    ) -> None:
        self.similarity_threshold = similarity_threshold
        self.max_entries = max_entries
        self.max_age_seconds = max_age_seconds
        self._ttl_seconds = max(1, int(max_age_seconds))  # Redis requires int >= 1
        self._client = None  # lazy

    # ---- internal ----

    def _redis(self):
        """Return (and lazily initialise) the Redis client."""
        if self._client is None:
            import redis  # noqa: PLC0415 — intentional lazy import

            self._client = redis.from_url(os.environ["REDIS_URL"])
        return self._client

    # ---- public API (mirrors SemanticCache) ----

    def lookup(self, query: str, *, scope: str | None = None) -> CacheHit | None:
        """Return a ``CacheHit`` for an exact normalized-query match, or ``None``.

        Scope isolation is enforced at the key level: a lookup for scope A
        will never match an entry stored under scope B, even if the
        normalized query text is identical.
        """
        normalized = _normalize(query)
        if not normalized:
            return None

        key = _redis_key(scope, normalized)
        raw = self._redis().get(key)
        if raw is None:
            return None

        data: dict = json.loads(raw)
        age = time.time() - data["ts"]

        return CacheHit(
            answer=data["answer"],
            similarity=1.0,          # exact match — similarity is always 1.0
            age_seconds=age,
            original_intent=data["intent"],
            original_confidence=data["confidence"],
            cached_query=normalized,
        )

    def store(
        self,
        query: str,
        answer: str,
        *,
        intent: str = "unknown",
        confidence: float = 0.0,
        scope: str | None = None,
    ) -> None:
        """Persist an entry to Redis with TTL = ``max_age_seconds``.

        Returns ``None`` (not a ``CacheEntry``) because ``CacheEntry``
        carries an embedding that is meaningless in the Redis adapter.
        Callers that type-check the return value should use ``CacheEntry |
        None`` or duck-type on the fields they actually need.
        """
        normalized = _normalize(query)
        if not normalized:
            return None

        key = _redis_key(scope, normalized)
        payload = json.dumps({
            "answer": answer,
            "intent": intent,
            "confidence": confidence,
            "ts": time.time(),
        })
        self._redis().setex(key, self._ttl_seconds, payload)
        return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_cache(fallback):
    """Return ``RedisSemanticCache()`` if ``REDIS_URL`` is set, else ``fallback``.

    This is the single wiring point for swapping the in-process cache with
    the Redis adapter.  Call it at startup; pass the existing
    ``SemanticCache()`` instance as ``fallback``.

    Example (NOT yet wired anywhere — see docs/SCALE_WIRING.md)::

        from bridge.scale.cache_redis import get_cache
        from lub.connectors.bridge.memory import SemanticCache

        _cache = get_cache(SemanticCache())
    """
    if os.environ.get("REDIS_URL"):
        return RedisSemanticCache()
    return fallback
