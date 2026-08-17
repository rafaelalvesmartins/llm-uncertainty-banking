# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for ``lub.connectors.bridge.memory``."""

from __future__ import annotations

import time

import pytest

from lub.connectors.bridge.memory import CacheHit, SemanticCache

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestCacheConstruction:
    def test_default_construction(self) -> None:
        cache = SemanticCache()
        assert cache.size == 0
        assert cache.hit_rate == 0.0

    def test_invalid_threshold_raises(self) -> None:
        with pytest.raises(ValueError, match="similarity_threshold"):
            SemanticCache(similarity_threshold=0)
        with pytest.raises(ValueError, match="similarity_threshold"):
            SemanticCache(similarity_threshold=1.5)

    def test_invalid_max_entries_raises(self) -> None:
        with pytest.raises(ValueError, match="max_entries"):
            SemanticCache(max_entries=0)


# ---------------------------------------------------------------------------
# Store and lookup
# ---------------------------------------------------------------------------


class TestStoreAndLookup:
    def test_empty_cache_misses(self) -> None:
        cache = SemanticCache()
        result = cache.lookup("qual meu saldo?")
        assert result is None

    def test_exact_match_hits(self) -> None:
        cache = SemanticCache()
        cache.store("qual meu saldo?", "R$ 12.450,32", intent="balance", confidence=0.9)

        result = cache.lookup("qual meu saldo?")
        assert isinstance(result, CacheHit)
        assert result.answer == "R$ 12.450,32"
        assert result.original_intent == "balance"
        assert result.similarity > 0.99

    def test_near_match_hits(self) -> None:
        cache = SemanticCache(similarity_threshold=0.5)
        cache.store(
            "qual meu saldo da conta corrente",
            "R$ 12.450,32",
            intent="balance",
        )
        # Same words, different order
        result = cache.lookup("saldo da minha conta corrente, qual?")
        assert result is not None

    def test_unrelated_query_misses(self) -> None:
        cache = SemanticCache(similarity_threshold=0.5)
        cache.store("qual meu saldo da conta corrente", "R$ 12.450")

        result = cache.lookup("quero pedir um emprestimo pessoal de longo prazo")
        # Different vocabulary, should not hit even at lower threshold
        assert result is None

    def test_store_returns_entry(self) -> None:
        cache = SemanticCache()
        entry = cache.store("test query", "test answer", intent="general")
        assert entry.answer == "test answer"
        assert entry.intent == "general"
        assert entry.hit_count == 0

    def test_hit_increments_hit_count(self) -> None:
        cache = SemanticCache()
        entry = cache.store("qual meu saldo?", "R$ 100")

        cache.lookup("qual meu saldo?")
        cache.lookup("qual meu saldo?")
        assert entry.hit_count == 2


# ---------------------------------------------------------------------------
# PII scrubbing
# ---------------------------------------------------------------------------


class TestPIIScrubbing:
    def test_cpf_does_not_pollute_embedding(self) -> None:
        """Same query with different CPFs should still hit the cache."""
        cache = SemanticCache(similarity_threshold=0.7)
        cache.store(
            "consultar dados do CPF 123.456.789-10",
            "Dados consultados",
            intent="lookup",
        )

        result = cache.lookup("consultar dados do CPF 987.654.321-00")
        assert result is not None

    def test_account_numbers_redacted(self) -> None:
        """Same query with different accounts should still hit."""
        cache = SemanticCache(similarity_threshold=0.7)
        cache.store("ver saldo da conta 12345-6", "R$ 100")

        result = cache.lookup("ver saldo da conta 99999-9")
        assert result is not None


# ---------------------------------------------------------------------------
# TTL / aging
# ---------------------------------------------------------------------------


class TestExpiry:
    def test_expired_entry_does_not_hit(self) -> None:
        cache = SemanticCache(max_age_seconds=0.05)
        cache.store("test", "answer")
        time.sleep(0.1)
        assert cache.lookup("test") is None

    def test_fresh_entry_does_hit(self) -> None:
        cache = SemanticCache(max_age_seconds=10.0)
        cache.store("test", "answer")
        result = cache.lookup("test")
        assert result is not None


# ---------------------------------------------------------------------------
# Eviction
# ---------------------------------------------------------------------------


class TestEviction:
    def test_max_entries_enforced(self) -> None:
        cache = SemanticCache(max_entries=3)
        cache.store("query 1", "a1")
        cache.store("query 2", "a2")
        cache.store("query 3", "a3")
        cache.store("query 4", "a4")
        assert cache.size == 3

    def test_oldest_evicted_first(self) -> None:
        cache = SemanticCache(max_entries=2, similarity_threshold=0.9)
        cache.store("the original query about balances", "first")
        cache.store("the second query about transfers", "second")
        cache.store("the third query about loans", "third")

        # Oldest gone; lookup of its content should miss
        assert cache.lookup("the original query about balances") is None
        # Newer entries remain
        assert cache.lookup("the third query about loans") is not None


# ---------------------------------------------------------------------------
# Clear and stats
# ---------------------------------------------------------------------------


class TestClearAndStats:
    def test_clear_returns_count_removed(self) -> None:
        cache = SemanticCache()
        cache.store("a", "1")
        cache.store("b", "2")
        cache.store("c", "3")
        n = cache.clear()
        assert n == 3
        assert cache.size == 0

    def test_clear_empty_returns_zero(self) -> None:
        cache = SemanticCache()
        assert cache.clear() == 0

    def test_stats_includes_required_keys(self) -> None:
        cache = SemanticCache()
        cache.store("test", "answer")
        cache.lookup("test")
        cache.lookup("xyzzy nothing here")

        stats = cache.stats()
        for key in ("entries", "max_entries", "hits", "misses", "hit_rate"):
            assert key in stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_hit_rate_correct(self) -> None:
        cache = SemanticCache()
        cache.store("query", "answer")
        cache.lookup("query")  # hit
        cache.lookup("query")  # hit
        cache.lookup("totally unrelated text here")  # miss
        assert cache.hit_rate == pytest.approx(2 / 3, abs=0.01)
