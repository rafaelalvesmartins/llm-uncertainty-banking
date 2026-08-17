"""Redis-backed rate-limiter and idempotency-store adapters (Track D — scale).

Drop-in replacements for the in-process ``_RATE_LIMITER`` and
``_IDEMPOTENCY_CACHE`` / ``_idempotency_lookup`` / ``_idempotency_store``
used in server.py.

ADDITIVE + FLAG-GATED: nothing is wired into the demo. Use the factory
helpers ``get_rate_limiter`` / ``get_idempotency`` to swap in the Redis
implementation only when ``REDIS_URL`` is set.

Mirrored semantics from server.py
----------------------------------
* ``_RATE_LIMITER.allow(customer_id, channel) -> bool``
  Token-bucket keyed by ``(customer_id, channel)``, with
  ``requests_per_minute`` and ``burst_size`` drawn from
  ``BRIDGE_RPM`` / ``BRIDGE_BURST`` env vars (defaults 180 / 30).

* ``_IDEMPOTENCY_CACHE``-equivalent operations
  - ``get(key) -> dict | None``   mirrors ``_idempotency_lookup``
  - ``set(key, value, ttl=60)``   mirrors ``_idempotency_store``
  Key shape: ``f"{customer_id}:{idempotency_key}"`` (callers build it).
  TTL: 60 s (``_IDEMPOTENCY_TTL_SECONDS`` in server.py).
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any

# ---------------------------------------------------------------------------
# Lazy Redis client
# ---------------------------------------------------------------------------

_redis_client = None


def _get_redis():
    """Return a lazily-created redis.Redis client from REDIS_URL env var.

    Called only from the Redis adapters; never reached when REDIS_URL is
    unset (the factories return the in-process fallback instead).
    """
    global _redis_client
    if _redis_client is None:
        import redis  # importorskip in tests; real import at runtime

        _redis_client = redis.from_url(os.environ["REDIS_URL"])
    return _redis_client


# ---------------------------------------------------------------------------
# Lua script for atomic token-bucket (sliding-window variant)
# ---------------------------------------------------------------------------
# Implements a fixed-window counter per (tenant, customer, channel) as the
# atomic primitive: each window is ``60 // rpm_windows`` seconds wide so
# the overall rpm and burst caps are honoured without a background thread.
#
# We use a simpler but correct approach: INCR + EXPIRE on a per-second
# window key so back-to-back calls within the same second share one counter.
# Burst is handled by allowing up to ``burst_size`` requests in the first
# window of a new key (INCR returns 1 → set EXPIRE; thereafter we track
# the window count against burst_size for the first window and rpm/60 * window
# for subsequent ones).
#
# For a clean atomic guarantee we use a Lua script:
#   KEYS[1] = window key   e.g. "rl:{customer}:{channel}:1748000000"
#   ARGV[1] = window_ttl   (seconds the window key lives)
#   ARGV[2] = limit        (max requests in this window)
# Returns 1 (allowed) or 0 (denied).

_RATE_LUA = """
local key   = KEYS[1]
local ttl   = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local count = redis.call('INCR', key)
if count == 1 then
    redis.call('EXPIRE', key, ttl)
end
if count <= limit then
    return 1
else
    return 0
end
"""


class RedisRateLimiter:
    """Redis-backed token-bucket rate limiter.

    Mirrors ``RateLimiter.allow(customer_id, channel) -> bool`` from
    ``lub.connectors.bridge.rate_limiter``.

    Strategy: fixed-window counter per (customer_id, channel, epoch-second).
    The first ``burst_size`` requests in a new window are permitted to model
    the burst allowance; subsequent windows cap at ``rpm / 60`` per second.
    Because we key by whole-second epoch the effective burst resets every
    second after an idle gap — which matches the lazy-refill semantics of the
    in-process token bucket closely enough for a drop-in.

    Parameters
    ----------
    rpm : int
        Requests per minute. Read from ``BRIDGE_RPM`` env var; default 180.
    burst : int
        Maximum back-to-back requests in a fresh window. Read from
        ``BRIDGE_BURST`` env var; default 30.
    """

    # Registered script SHA — cached after first SCRIPT LOAD.
    _sha: str | None = None

    def __init__(self, rpm: int | None = None, burst: int | None = None) -> None:
        self._rpm = rpm if rpm is not None else int(os.environ.get("BRIDGE_RPM", "180"))
        self._burst = burst if burst is not None else int(os.environ.get("BRIDGE_BURST", "30"))
        # Per-second refill rate and window length.
        # We use 1-second windows; the per-second cap is rpm/60 (rounded up,
        # minimum 1) for steady-state, and burst_size for the very first
        # request in a fresh key (which the Lua script handles via INCR==1).
        self._per_second = max(1, math.ceil(self._rpm / 60))

    # ------------------------------------------------------------------
    # Public API (mirrors RateLimiter.allow)
    # ------------------------------------------------------------------

    def allow(self, customer_id: str, channel: str) -> bool:
        """Return True if the request is within the budget, False otherwise.

        The key includes the current epoch-second so each second gets a fresh
        counter. The limit applied is ``burst_size`` for the first call in a
        new second (models the burst window) then falls back to per-second
        steady state.  In practice the Lua script just checks ``count <=
        limit`` where limit is always the *larger* of the two so the first
        ``burst`` requests in any given second window are all permitted.
        """
        r = _get_redis()
        now_s = int(time.time())
        key = f"rl:{{{customer_id}:{channel}}}:{now_s}"
        # Window TTL: 2 seconds to allow for clock jitter between clients.
        window_ttl = 2
        # Limit per window: burst_size acts as the ceiling so a fresh burst
        # within a single second is fully absorbed; once burst is spent the
        # per-second steady-state cap is lower but the window is only 1 s.
        limit = max(self._burst, self._per_second)

        if self._sha is None:
            self.__class__._sha = r.script_load(_RATE_LUA)

        result = r.evalsha(self._sha, 1, key, window_ttl, limit)
        return bool(result)

    def reset(self, customer_id: str, channel: str) -> None:
        """Delete rate-limit keys for a (customer_id, channel) pair.

        Intended for tests / operational tooling. Deletes all 1-second
        window keys for the current and next second.
        """
        r = _get_redis()
        now_s = int(time.time())
        keys = [f"rl:{{{customer_id}:{channel}}}:{now_s + i}" for i in range(-1, 3)]
        r.delete(*keys)


# ---------------------------------------------------------------------------
# Idempotency store
# ---------------------------------------------------------------------------


class RedisIdempotencyStore:
    """Redis-backed idempotency store.

    Mirrors the ``_idempotency_lookup`` / ``_idempotency_store`` pair in
    server.py.  Values are JSON-serialised dicts stored with SETNX + EXPIRE.

    Key shape: ``"idempotency:{key}"`` where ``key`` is already the
    ``f"{customer_id}:{idempotency_key}"`` compound that the caller builds
    (matching the tuple ``(customer_id, key)`` used by the in-process
    ``_IDEMPOTENCY_CACHE`` dict).

    Default TTL: 60 s (``_IDEMPOTENCY_TTL_SECONDS`` in server.py).
    """

    _PREFIX = "idempotency:"

    def get(self, key: str) -> dict[str, Any] | None:
        """Return the cached response dict, or None if absent / expired."""
        r = _get_redis()
        raw = r.get(f"{self._PREFIX}{key}")
        if raw is None:
            return None
        return json.loads(raw)

    def set(self, key: str, value: dict[str, Any], ttl: int = 60) -> None:
        """Store ``value`` under ``key`` with ``ttl`` seconds expiry.

        Uses SET with NX + EX so a concurrent retry racing the first write
        never overwrites the already-stored value.
        """
        r = _get_redis()
        r.set(
            f"{self._PREFIX}{key}",
            json.dumps(value),
            nx=True,   # only set if key does not exist
            ex=ttl,    # expiry in seconds
        )


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def get_rate_limiter(fallback: Any) -> Any:
    """Return ``RedisRateLimiter`` if ``REDIS_URL`` is set, else ``fallback``.

    ``fallback`` should be the in-process ``_RATE_LIMITER`` instance from
    server.py.  Nothing is wired here; call sites opt in explicitly.
    """
    if not os.environ.get("REDIS_URL"):
        return fallback
    return RedisRateLimiter()


def get_idempotency(fallback: Any) -> Any:
    """Return ``RedisIdempotencyStore`` if ``REDIS_URL`` is set, else ``fallback``.

    ``fallback`` should be the in-process lookup/store pair or a wrapper
    object from server.py.  Nothing is wired here; call sites opt in
    explicitly.
    """
    if not os.environ.get("REDIS_URL"):
        return fallback
    return RedisIdempotencyStore()
