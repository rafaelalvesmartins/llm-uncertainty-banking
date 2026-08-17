# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""B3 regression — the cache must never serve a withheld answer.

A balance cached under PASSTHROUGH (low threshold) must NOT leak through a
re-derived REASK/ESCALATE decision when the threshold is later raised — the
guard re-decides the label on a cache hit, so the served body must be re-gated
the same way the fresh path gates it.

Run from the project root::

    pytest bridge-ui/backend/test_cache_confidentiality.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402

_SALDO = "Quero ver o saldo da minha conta"


def _no_db() -> None:
    raise RuntimeError("test: sqlite disabled")


def _fresh_cache() -> server.SemanticCache:
    return server.SemanticCache(similarity_threshold=0.85, max_entries=200, max_age_seconds=300.0)


def _q() -> server.QueryRequest:
    return server.QueryRequest(query=_SALDO, customer_id="demo", channel="whatsapp")


def test_cache_hit_does_not_leak_answer_under_reask(monkeypatch) -> None:
    monkeypatch.setattr(server, "_audit_db", _no_db)
    monkeypatch.setattr(server, "_CACHE", _fresh_cache())
    monkeypatch.setattr(server, "_RUNTIME_CACHE_ENABLED", True)

    # Low threshold: the balance is released (PASSTHROUGH) and cached.
    monkeypatch.setattr(server, "_RUNTIME_GUARD_THRESHOLD", 0.10)
    first = server.query(_q())
    assert first.decision == "PASSTHROUGH"
    assert "12,450" in first.answer

    # Raise the bar: the SAME query now re-derives to REASK on the cache hit.
    monkeypatch.setattr(server, "_RUNTIME_GUARD_THRESHOLD", 0.95)
    second = server.query(_q())
    assert second.cache_hit is True
    assert second.decision == "REASK"
    # The cached balance must NOT be served under a REASK label (the B3 leak).
    assert "12,450" not in second.answer
    assert "confidence" in second.answer.lower()


def test_fresh_reask_also_withholds_the_answer(monkeypatch) -> None:
    monkeypatch.setattr(server, "_audit_db", _no_db)
    monkeypatch.setattr(server, "_CACHE", _fresh_cache())
    monkeypatch.setattr(server, "_RUNTIME_CACHE_ENABLED", False)  # force the fresh path
    monkeypatch.setattr(server, "_RUNTIME_GUARD_THRESHOLD", 0.95)
    out = server.query(_q())
    assert out.decision == "REASK"
    assert "12,450" not in out.answer


def test_cache_is_scoped_per_customer(monkeypatch) -> None:
    """R1 regression (architecture audit 2026-06-14): one customer must never be
    served another customer's cached answer.

    The semantic cache is keyed by customer_id scope, so an identical,
    non-RESTRICTED query (e.g. "qual meu saldo?") from a DIFFERENT customer is a
    MISS, not a HIT — even though the query text + embedding are identical and the
    RESTRICTED/PII bypass does not fire for a balance question. Detected via the
    cache_hit flag (the fake backend's answer string is the same for everyone, so
    isolation has to be asserted on the hit, not the body).
    """
    monkeypatch.setattr(server, "_audit_db", _no_db)
    monkeypatch.setattr(server, "_CACHE", _fresh_cache())
    monkeypatch.setattr(server, "_RUNTIME_CACHE_ENABLED", True)
    monkeypatch.setattr(server, "_RUNTIME_GUARD_THRESHOLD", 0.10)  # release + cache

    def _ask(cid: str):
        return server.query(server.QueryRequest(query=_SALDO, customer_id=cid, channel="whatsapp"))

    a1 = _ask("C001-PF-padrao")
    assert a1.cache_hit is False  # fresh; now cached under scope C001
    a2 = _ask("C001-PF-padrao")
    assert a2.cache_hit is True  # same customer + query -> hit (scoping doesn't break intra-customer reuse)
    b1 = _ask("C002-PJ-mei")
    assert b1.cache_hit is False  # different customer, identical query -> MISS, no cross-customer leak
