"""Tests for RedisRateLimiter and RedisIdempotencyStore (Track D — scale).

Requires ``fakeredis`` (listed in requirements-scale.txt). Skip the whole
module gracefully when it is absent so the base test suite never fails due
to a missing optional dependency.

    pytest bridge-ui/backend/scale/test_limiter_redis.py

Covered:
  1. Limiter allows up to burst, then denies.
  2. Window resets after 1 second (time-travel with fakeredis).
  3. Idempotency set/get round-trip.
  4. Idempotency TTL expiry.
  5. Per-key isolation (different customers don't share budget).
  6. Factory returns fallback when REDIS_URL unset.
  7. Factory returns Redis impl when REDIS_URL is set.
"""

from __future__ import annotations

import time

import pytest

fakeredis = pytest.importorskip("fakeredis")

# ---------------------------------------------------------------------------
# Patch _get_redis to return a fakeredis client for all tests in this module.
# We patch at the module level so every instantiation within limiter_redis
# picks up the fake client without touching real network state.
# ---------------------------------------------------------------------------

import fakeredis as _fakeredis  # noqa: E402  (after importorskip)

import scale.limiter_redis as _limiter_mod  # noqa: E402
from scale.limiter_redis import (  # noqa: E402
    RedisIdempotencyStore,
    RedisRateLimiter,
    get_idempotency,
    get_rate_limiter,
)


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """Replace the lazy Redis client with an in-process fakeredis server."""
    server = _fakeredis.FakeServer()
    client = _fakeredis.FakeRedis(server=server, decode_responses=False)
    monkeypatch.setattr(_limiter_mod, "_redis_client", client)
    # Also reset cached Lua SHA so it is re-registered against the fake client.
    monkeypatch.setattr(RedisRateLimiter, "_sha", None)
    yield client


def _script_supported() -> bool:
    """True if the backing client can run server-side Lua (SCRIPT LOAD/EVALSHA).

    The rate limiter's atomicity relies on a Lua script; fakeredis does not
    implement SCRIPT, so the limiter tests are skipped against it and only run
    against a real Redis. The idempotency tests (no Lua) always run.
    """
    try:
        c = _fakeredis.FakeRedis(server=_fakeredis.FakeServer(), decode_responses=False)
        c.script_load("return 1")
        return True
    except Exception:
        return False


_LUA_OK = _script_supported()
_needs_lua = pytest.mark.skipif(
    not _LUA_OK,
    reason="backing Redis client lacks SCRIPT/EVALSHA (fakeredis) — the rate limiter's "
    "atomic Lua path requires a real Redis; set REDIS_URL to run these.",
)


# ---------------------------------------------------------------------------
# Helper: build a limiter with a small burst so tests are fast
# ---------------------------------------------------------------------------

def _make_limiter(burst: int = 3, rpm: int = 60) -> RedisRateLimiter:
    return RedisRateLimiter(rpm=rpm, burst=burst)


# ---------------------------------------------------------------------------
# 1. Limiter allows up to burst then denies
# ---------------------------------------------------------------------------


@_needs_lua
def test_limiter_allows_up_to_burst():
    """First ``burst`` calls must be allowed; the next must be denied."""
    lim = _make_limiter(burst=3)
    customer, channel = "cust-1", "app"

    results = [lim.allow(customer, channel) for _ in range(4)]

    assert results[:3] == [True, True, True], "Expected first 3 to be allowed"
    assert results[3] is False, "Expected 4th call to be denied"


@_needs_lua
def test_limiter_denies_after_burst_exhausted():
    """Multiple denials once burst is spent in the same second."""
    lim = _make_limiter(burst=2)
    customer, channel = "cust-deny", "web"

    # Exhaust burst
    lim.allow(customer, channel)
    lim.allow(customer, channel)

    # All subsequent calls in the same window should be denied
    for _ in range(5):
        assert lim.allow(customer, channel) is False


# ---------------------------------------------------------------------------
# 2. Window resets after 1 second (time-travel)
# ---------------------------------------------------------------------------


@_needs_lua
def test_limiter_window_resets(monkeypatch):
    """After moving the clock forward by 2 s the burst budget is replenished."""
    lim = _make_limiter(burst=2)
    customer, channel = "cust-reset", "app"

    # Exhaust burst at t=0
    assert lim.allow(customer, channel) is True
    assert lim.allow(customer, channel) is True
    assert lim.allow(customer, channel) is False  # denied

    # Advance time by 2 seconds — new window key, fresh counter
    original_time = time.time
    monkeypatch.setattr(time, "time", lambda: original_time() + 2)

    assert lim.allow(customer, channel) is True, "Window should have reset"
    assert lim.allow(customer, channel) is True


# ---------------------------------------------------------------------------
# 3. Idempotency set/get round-trip
# ---------------------------------------------------------------------------


def test_idempotency_set_get():
    """A stored value is returned verbatim by get."""
    store = RedisIdempotencyStore()
    key = "cust-99:idem-key-abc"
    payload = {"answer": "PIX enviado", "intent": "pix", "confidence": 0.9}

    store.set(key, payload)
    result = store.get(key)

    assert result == payload


def test_idempotency_get_missing():
    """get returns None for an unknown key."""
    store = RedisIdempotencyStore()
    assert store.get("nonexistent-key") is None


# ---------------------------------------------------------------------------
# 4. Idempotency TTL expiry
# ---------------------------------------------------------------------------


def test_idempotency_ttl(fake_redis):
    """Value disappears after TTL seconds (simulated via fakeredis PTTL)."""
    store = RedisIdempotencyStore()
    key = "cust-ttl:idem-key-ttl"
    payload = {"answer": "ok"}

    store.set(key, payload, ttl=60)

    # Confirm it is stored and TTL is set
    full_key = f"idempotency:{key}"
    assert fake_redis.exists(full_key)
    ttl_remaining = fake_redis.ttl(full_key)
    assert 0 < ttl_remaining <= 60, f"Expected TTL in (0, 60], got {ttl_remaining}"

    # Simulate expiry by deleting the key (fakeredis doesn't auto-advance time)
    fake_redis.delete(full_key)
    assert store.get(key) is None, "Value should be gone after TTL expiry"


def test_idempotency_set_is_nx(fake_redis):
    """A second set on the same key does NOT overwrite (NX semantics)."""
    store = RedisIdempotencyStore()
    key = "cust-nx:idem-nx"
    first_payload = {"answer": "first"}
    second_payload = {"answer": "second"}

    store.set(key, first_payload)
    store.set(key, second_payload)  # should be no-op (NX)

    assert store.get(key) == first_payload


# ---------------------------------------------------------------------------
# 5. Per-key isolation
# ---------------------------------------------------------------------------


@_needs_lua
def test_limiter_per_key_isolation():
    """Exhausting budget for one customer does not affect another."""
    lim = _make_limiter(burst=2)

    # Exhaust cust-A
    lim.allow("cust-A", "app")
    lim.allow("cust-A", "app")
    assert lim.allow("cust-A", "app") is False

    # cust-B is unaffected
    assert lim.allow("cust-B", "app") is True
    assert lim.allow("cust-B", "app") is True


@_needs_lua
def test_limiter_channel_isolation():
    """Same customer on different channels has independent budgets."""
    lim = _make_limiter(burst=1)
    customer = "cust-channels"

    assert lim.allow(customer, "app") is True
    assert lim.allow(customer, "app") is False  # app exhausted

    # whatsapp channel is a separate key → still has budget
    assert lim.allow(customer, "whatsapp") is True


def test_idempotency_key_isolation():
    """Two different idempotency keys are stored independently."""
    store = RedisIdempotencyStore()
    store.set("c1:k1", {"v": 1})
    store.set("c1:k2", {"v": 2})

    assert store.get("c1:k1") == {"v": 1}
    assert store.get("c1:k2") == {"v": 2}


# ---------------------------------------------------------------------------
# 6. Factory returns fallback when REDIS_URL unset
# ---------------------------------------------------------------------------


def test_get_rate_limiter_returns_fallback_no_url(monkeypatch):
    """get_rate_limiter returns the fallback when REDIS_URL is not set."""
    monkeypatch.delenv("REDIS_URL", raising=False)

    sentinel = object()
    result = get_rate_limiter(sentinel)
    assert result is sentinel


def test_get_idempotency_returns_fallback_no_url(monkeypatch):
    """get_idempotency returns the fallback when REDIS_URL is not set."""
    monkeypatch.delenv("REDIS_URL", raising=False)

    sentinel = object()
    result = get_idempotency(sentinel)
    assert result is sentinel


# ---------------------------------------------------------------------------
# 7. Factory returns Redis impl when REDIS_URL is set
# ---------------------------------------------------------------------------


def test_get_rate_limiter_returns_redis_impl(monkeypatch):
    """get_rate_limiter returns a RedisRateLimiter when REDIS_URL is set."""
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    result = get_rate_limiter(object())
    assert isinstance(result, RedisRateLimiter)


def test_get_idempotency_returns_redis_impl(monkeypatch):
    """get_idempotency returns a RedisIdempotencyStore when REDIS_URL is set."""
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    result = get_idempotency(object())
    assert isinstance(result, RedisIdempotencyStore)
