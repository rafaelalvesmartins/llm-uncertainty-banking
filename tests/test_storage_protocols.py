# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""Tests for the storage Protocols shipped in passes 36-38.

Per spec 31, these are *additive* surfaces: the Protocols, an
InMemory test double for each, and structural-conformance asserts
that the existing concrete implementations (TieredRouter, EvidenceStore,
Ledger) satisfy them. No consumers were touched.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Pass 36 — RouterPolicy
# ---------------------------------------------------------------------------


def test_router_policy_protocol_exists():
    from lub.orchestration.router_protocol import RouterPolicy
    assert RouterPolicy is not None


def test_router_registry_validates_inputs():
    from lub.orchestration.router_protocol import (
        get_router_policy,
        register_router_policy,
    )

    class Stub:
        def answer(self, q): return "stub"

    register_router_policy("stub", Stub())
    assert get_router_policy("stub").answer({}) == "stub"

    with pytest.raises(ValueError, match="non-empty"):
        register_router_policy("", Stub())
    with pytest.raises(TypeError, match="answer"):
        register_router_policy("bad", object())  # type: ignore[arg-type]
    with pytest.raises(KeyError, match="nope"):
        get_router_policy("nope")


def test_existing_failover_chain_satisfies_router_policy_structurally():
    """FailoverChain must structurally satisfy RouterPolicy (has .answer)."""
    from lub.orchestration.router import FailoverChain  # noqa: F401
    # Just check the attribute exists at the class level; instantiating
    # FailoverChain requires real TieredRouters which need backends.
    assert callable(getattr(FailoverChain, "answer", None))


# ---------------------------------------------------------------------------
# Pass 37 — EvidenceStoreProtocol + InMemoryEvidenceStore
# ---------------------------------------------------------------------------


def test_evidence_store_protocol_exists():
    from lub.evidence.protocols import EvidenceStoreProtocol
    assert EvidenceStoreProtocol is not None


def test_in_memory_evidence_store_satisfies_protocol():
    from lub.evidence.protocols import EvidenceStoreProtocol, InMemoryEvidenceStore
    store = InMemoryEvidenceStore()
    assert isinstance(store, EvidenceStoreProtocol)


def test_in_memory_evidence_store_basic_round_trip():
    from lub.evidence.protocols import InMemoryEvidenceStore
    s = InMemoryEvidenceStore()
    s.add("Is X true?", "yes", correct=True, uq_scores={"p_true": 0.9})
    s.add("Is Y true?", "no", correct=False, uq_scores={"p_true": 0.4})
    s.add("Is X false?", "no", correct=True, uq_scores={"p_true": 0.7})
    assert len(s) == 3
    hits = s.query("Is X true?", k=2)
    # Top hit should be the exact-match question.
    assert hits[0]["question"] == "Is X true?"
    assert len(hits) == 2


def test_in_memory_evidence_store_drift_events():
    from lub.evidence.protocols import InMemoryEvidenceStore
    s = InMemoryEvidenceStore()
    s.record_drift_event({"event": "psi_breach", "psi": 0.21})
    s.record_drift_event({"event": "psi_breach", "psi": 0.18})
    events = list(s.drift_events())
    assert len(events) == 2
    assert events[0]["psi"] == 0.21


def test_existing_evidence_store_satisfies_protocol():
    """The real EvidenceStore (TF-IDF) must structurally satisfy the Protocol."""
    from lub.evidence.protocols import EvidenceStoreProtocol
    from lub.evidence.store import EvidenceStore
    store = EvidenceStore(dim=64)
    assert isinstance(store, EvidenceStoreProtocol)


# ---------------------------------------------------------------------------
# Pass 38 — LedgerProtocol + InMemoryLedger
# ---------------------------------------------------------------------------


def test_ledger_protocol_exists():
    from lub.ledger.protocol import LedgerProtocol
    assert LedgerProtocol is not None


def test_in_memory_ledger_satisfies_protocol():
    from lub.ledger.protocol import InMemoryLedger, LedgerProtocol
    led = InMemoryLedger()
    assert isinstance(led, LedgerProtocol)


def test_in_memory_ledger_round_trip():
    from lub.ledger.protocol import InMemoryLedger
    ledger = InMemoryLedger()
    qid = ledger.log_query("Q?", domain="banking")
    aid = ledger.log_answer(qid, "gpt-4o", "openai", "yes", tier="prime")
    sid = ledger.log_score(aid, "p_true", 0.92)
    pid = ledger.log_policy(aid, "EMIT", 0.7, True, "ok")
    ledger.update_outcome(aid, correct=True)

    assert qid > 0 and aid > qid and sid > aid and pid > sid
    fetched = ledger.fetch_answer(aid)
    assert fetched is not None and fetched["model"] == "gpt-4o"
    scores = ledger.fetch_scores(aid)
    assert len(scores) == 1 and scores[0]["method"] == "p_true"
    assert ledger._outcomes[aid]["correct"] == 1


def test_existing_ledger_satisfies_protocol(tmp_path):
    """The real Ledger (sqlite) must structurally satisfy the Protocol."""
    from lub.ledger import Ledger
    from lub.ledger.protocol import LedgerProtocol
    led = Ledger(tmp_path / "uq.db")
    try:
        assert isinstance(led, LedgerProtocol)
    finally:
        led.close()


# ---------------------------------------------------------------------------
# Cross-Protocol smoke: InMemoryLedger + dashboard via SnapshotSource Protocol
# ---------------------------------------------------------------------------


def test_in_memory_ledger_does_not_satisfy_snapshot_source_directly():
    """SnapshotSource is a different Protocol (4 kpi_* methods); ensure
    we don't accidentally treat InMemoryLedger as one. A dedicated
    InMemorySnapshotSource shim would be the right plug-in."""
    from lub.dashboard.protocols import SnapshotSource
    from lub.ledger.protocol import InMemoryLedger
    led = InMemoryLedger()
    # InMemoryLedger does NOT expose kpi_decisions etc., so it must NOT
    # satisfy SnapshotSource. This guards against accidental Protocol
    # collision where a class drifts into satisfying both unintentionally.
    assert not isinstance(led, SnapshotSource)
