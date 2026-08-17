"""Tests for the Redis-backed semantic cache adapter (Track D / scale).

Requires ``fakeredis>=2.20`` (already listed in requirements-scale.txt).
The entire module is skipped when fakeredis is not installed so the base
test suite (``pip install -r requirements.txt``) never fails here.

Run with a real Redis to validate TTL precision and network behaviour:
    REDIS_URL=redis://localhost:6379/0 pytest scale/test_cache_redis.py -v
"""

from __future__ import annotations

import time

import pytest

fakeredis = pytest.importorskip("fakeredis")

# ---------------------------------------------------------------------------
# Patch redis.from_url before importing the module under test so the module's
# lazy client creation resolves to the fakeredis server.
# ---------------------------------------------------------------------------

import fakeredis as _fakeredis  # noqa: E402  (must follow importorskip)


@pytest.fixture()
def fake_redis_server(monkeypatch):
    """Return a FakeRedis server instance and patch redis.from_url."""
    server = _fakeredis.FakeServer()
    fake_client = _fakeredis.FakeRedis(server=server)

    import redis as _redis  # noqa: PLC0415

    monkeypatch.setattr(_redis, "from_url", lambda url, **kw: fake_client)
    return fake_client


@pytest.fixture()
def cache(fake_redis_server, monkeypatch):
    """RedisSemanticCache wired to the fake Redis, REDIS_URL set."""
    monkeypatch.setenv("REDIS_URL", "redis://fake/0")

    # Import after patching so the lazy client picks up the monkeypatch.
    from scale.cache_redis import RedisSemanticCache  # noqa: PLC0415

    return RedisSemanticCache(max_age_seconds=60.0)


# ---------------------------------------------------------------------------
# Test: store → lookup hit
# ---------------------------------------------------------------------------


def test_store_then_lookup_returns_hit(cache):
    """Storing an entry and looking it up with the identical query returns a hit."""
    cache.store("Qual meu saldo?", "Seu saldo é R$ 1.000.", intent="balance_query", confidence=0.95)
    hit = cache.lookup("Qual meu saldo?")

    assert hit is not None
    assert hit.answer == "Seu saldo é R$ 1.000."
    assert hit.original_intent == "balance_query"
    assert hit.original_confidence == pytest.approx(0.95)
    assert hit.similarity == pytest.approx(1.0)
    assert hit.cached_query == "qual meu saldo?"  # normalized
    assert 0 <= hit.age_seconds < 5  # fresh


def test_lookup_normalises_query(cache):
    """Lookup should normalise the query before matching (case, whitespace)."""
    cache.store("saldo atual", "R$ 500.", intent="balance_query", confidence=0.9)

    # Different casing and extra whitespace — must still hit.
    hit = cache.lookup("  SALDO   ATUAL  ")
    assert hit is not None
    assert hit.answer == "R$ 500."


def test_lookup_miss_on_different_query(cache):
    """A lookup for a different normalized query returns None."""
    cache.store("Qual meu saldo?", "R$ 1.000.", intent="balance_query", confidence=0.9)
    hit = cache.lookup("Quero transferir dinheiro")
    assert hit is None


def test_lookup_empty_query_returns_none(cache):
    """An empty (or whitespace-only) query returns None without touching Redis."""
    hit = cache.lookup("")
    assert hit is None

    hit2 = cache.lookup("   ")
    assert hit2 is None


# ---------------------------------------------------------------------------
# Test: scope isolation (R1 guarantee)
# ---------------------------------------------------------------------------


def test_scope_isolation_miss(cache):
    """An entry stored under scope A must NOT be returned for scope B."""
    cache.store("ver saldo", "R$ 200.", intent="balance_query", confidence=0.8, scope="customer_A")

    # Same query, different scope → must miss.
    hit = cache.lookup("ver saldo", scope="customer_B")
    assert hit is None


def test_scope_isolation_hit(cache):
    """An entry stored under scope A IS returned for scope A."""
    cache.store("ver saldo", "R$ 200.", intent="balance_query", confidence=0.8, scope="customer_A")

    hit = cache.lookup("ver saldo", scope="customer_A")
    assert hit is not None
    assert hit.answer == "R$ 200."


def test_scope_none_does_not_leak_to_scoped(cache):
    """An entry stored with scope=None must not be returned for a named scope."""
    cache.store("extrato", "Sem movimentações.", intent="statement", confidence=0.7, scope=None)

    hit = cache.lookup("extrato", scope="customer_X")
    assert hit is None


def test_scoped_does_not_leak_to_scope_none(cache):
    """An entry stored with a named scope must not be returned for scope=None."""
    cache.store("extrato", "Movimentações...", intent="statement", confidence=0.7, scope="customer_X")

    hit = cache.lookup("extrato", scope=None)
    assert hit is None


def test_separate_scopes_independent(cache):
    """Two scopes can store the same query with different answers independently."""
    cache.store("saldo", "R$ 100.", intent="balance_query", confidence=0.9, scope="A")
    cache.store("saldo", "R$ 999.", intent="balance_query", confidence=0.9, scope="B")

    hit_a = cache.lookup("saldo", scope="A")
    hit_b = cache.lookup("saldo", scope="B")

    assert hit_a is not None and hit_a.answer == "R$ 100."
    assert hit_b is not None and hit_b.answer == "R$ 999."


# ---------------------------------------------------------------------------
# Test: TTL / miss after expiry
# ---------------------------------------------------------------------------


def test_ttl_miss_after_expiry(monkeypatch):
    """Entry stored with a 1-second TTL must miss after expiry.

    Uses a dedicated FakeServer so we can advance its clock without a
    real sleep.  Falls back to a 2-second sleep when the clock attribute
    is not available (older fakeredis builds or real-Redis CI runs).
    """
    monkeypatch.setenv("REDIS_URL", "redis://fake/0")

    server = _fakeredis.FakeServer()
    fake_client = _fakeredis.FakeRedis(server=server)

    import redis as _redis  # noqa: PLC0415

    monkeypatch.setattr(_redis, "from_url", lambda url, **kw: fake_client)

    from scale.cache_redis import RedisSemanticCache  # noqa: PLC0415

    short_cache = RedisSemanticCache(max_age_seconds=1.0)

    short_cache.store("saldo", "R$ 50.", intent="balance_query", confidence=0.8)

    # Immediately should hit.
    assert short_cache.lookup("saldo") is not None

    # Advance the fakeredis internal clock by 2 seconds so the TTL fires.
    # fakeredis >= 2.20 exposes the server's clock via the `_time` attribute.
    if hasattr(server, "_time"):
        server._time += 2
        assert short_cache.lookup("saldo") is None
    else:
        # Fallback: real sleep (slow but correct on real Redis in CI).
        time.sleep(2)
        assert short_cache.lookup("saldo") is None


# ---------------------------------------------------------------------------
# Test: get_cache() factory
# ---------------------------------------------------------------------------


def test_get_cache_returns_fallback_when_no_redis_url(monkeypatch):
    """get_cache(fallback) returns fallback when REDIS_URL is not set."""
    monkeypatch.delenv("REDIS_URL", raising=False)

    from scale.cache_redis import get_cache  # noqa: PLC0415

    sentinel = object()
    result = get_cache(sentinel)
    assert result is sentinel


def test_get_cache_returns_redis_cache_when_redis_url_set(monkeypatch, fake_redis_server):
    """get_cache(fallback) returns a RedisSemanticCache when REDIS_URL is set."""
    monkeypatch.setenv("REDIS_URL", "redis://fake/0")

    from scale.cache_redis import RedisSemanticCache, get_cache  # noqa: PLC0415

    sentinel = object()
    result = get_cache(sentinel)
    assert isinstance(result, RedisSemanticCache)


def test_get_cache_ignores_fallback_when_redis_url_set(monkeypatch, fake_redis_server):
    """get_cache(fallback) does NOT return fallback when REDIS_URL is set."""
    monkeypatch.setenv("REDIS_URL", "redis://fake/0")

    from scale.cache_redis import get_cache  # noqa: PLC0415

    sentinel = object()
    result = get_cache(sentinel)
    assert result is not sentinel
