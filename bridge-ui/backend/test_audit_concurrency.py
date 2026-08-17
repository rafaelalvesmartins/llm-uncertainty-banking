# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""R4b regression (architecture audit 2026-06-14) — audit chain integrity under load.

The whole tamper-evidence thesis rests on _AUDIT_LOCK serializing the seq +
prev_hash read-modify-write in _audit_append. If that lock were wrong, concurrent
/query calls would either LOSE increments (final seq < total queries) or interleave
the hash links (chain verification fails). This drives many threads through the full
/query pipeline (fake backend) and asserts both invariants hold.

Run from the project root::

    pytest bridge-ui/backend/test_audit_concurrency.py -v
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402

try:
    from backend.routers import audit as audit_router  # noqa: E402
except ImportError:  # module-mode
    from routers import audit as audit_router  # type: ignore[no-redef]  # noqa: E402

# Use the SAME state.audit module object that server bound to. Re-importing it
# (flat `state.audit` vs package `backend.state.audit`) can resolve a SECOND module
# instance under pytest's sys.path, whose _AUDIT_SEQ would diverge from the one
# server.query() actually mutates. server._audit_state_mod is the canonical one.
audit_mod = server._audit_state_mod

THREADS = 8
PER_THREAD = 10


class _AllowAll:
    def allow(self, *_a, **_k) -> bool:
        return True


def _no_db() -> None:
    raise RuntimeError("test: sqlite disabled")


def test_audit_chain_is_consistent_under_concurrent_queries(monkeypatch) -> None:
    # Isolate audit state; skip SQLite (the in-memory chain + lock are what we test).
    monkeypatch.setattr(server, "_audit_db", _no_db)
    monkeypatch.setattr(server, "_RATE_LIMITER", _AllowAll())  # don't let the rate limiter drop queries
    monkeypatch.setattr(server, "_CACHE", server.SemanticCache(similarity_threshold=0.85, max_entries=2000, max_age_seconds=300.0))
    audit_mod._AUDIT.clear()
    audit_mod._AUDIT_SEQ = 0
    audit_mod._AUDIT_LAST_HASH = "0" * 64

    total = THREADS * PER_THREAD

    def _worker(t: int) -> None:
        for i in range(PER_THREAD):
            # distinct query+customer per call: every /query appends exactly one
            # audit entry on both the fresh and cache-hit paths.
            server.query(server.QueryRequest(
                query=f"consulta saldo t{t} n{i}",
                customer_id=f"conc-{t}",
                channel="app",
            ))

    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        list(ex.map(_worker, range(THREADS)))

    # 1) No lost or duplicated increments: the lock made seq advance exactly once
    #    per query. A broken lock would yield seq < total (lost-update race).
    assert audit_mod._AUDIT_SEQ == total, f"expected seq {total}, got {audit_mod._AUDIT_SEQ}"

    # 2) The hash chain is intact end-to-end: every prev_hash links to the prior
    #    entry's hash. An interleaved append under a broken lock would break this.
    verdict = audit_router.audit_verify(source="memory")
    assert verdict["valid"] is True, verdict.get("first_failure")
    assert verdict["checked"] == total

    # 3) seq values are exactly 1..total with no gaps or repeats.
    seqs = sorted(e["seq"] for e in list(audit_mod._AUDIT))
    assert seqs == list(range(1, total + 1))
