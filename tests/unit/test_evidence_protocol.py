# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Hermetic tests for ``lub.evidence.protocols`` (Pattern 1.4)."""

from __future__ import annotations

from pathlib import Path

from lub.evidence import (
    EvidenceStore,
    EvidenceStoreProtocol,
    Neighbour,
    PersistentEvidenceStoreProtocol,
)

# ---------------------------------------------------------------------------
# Concrete EvidenceStore satisfies both protocols
# ---------------------------------------------------------------------------


def test_concrete_store_satisfies_evidence_store_protocol():
    store = EvidenceStore(dim=128)
    assert isinstance(store, EvidenceStoreProtocol)


def test_concrete_store_satisfies_persistent_protocol():
    store = EvidenceStore(dim=128)
    assert isinstance(store, PersistentEvidenceStoreProtocol)


# ---------------------------------------------------------------------------
# A minimal fake satisfies the Protocol via duck typing
# ---------------------------------------------------------------------------


class _FakeStore:
    """Minimal duck-typed fake — no numpy, no embeddings."""

    def __init__(self, dim: int = 16) -> None:
        self.dim = dim
        self._records: list[tuple[str, str, bool]] = []

    def __len__(self) -> int:
        return len(self._records)

    def add(
        self,
        question: str,
        answer: str,
        correct: bool,
        uq_scores: dict[str, float] | None = None,
    ) -> None:
        self._records.append((question, answer, correct))

    def query(self, question: str, k: int = 5) -> list[Neighbour]:
        # Returns up to k records as Neighbours with similarity 1.0.
        out = []
        for q, a, c in self._records[:k]:
            out.append(
                Neighbour(
                    question=q,
                    answer=a,
                    correct=c,
                    cosine_similarity=1.0,
                    uq_scores={},
                )
            )
        return out


def test_fake_store_satisfies_protocol():
    fake = _FakeStore()
    assert isinstance(fake, EvidenceStoreProtocol)


def test_fake_store_does_not_satisfy_persistent_protocol():
    # No save/load → must NOT pass the persistent protocol check.
    fake = _FakeStore()
    assert not isinstance(fake, PersistentEvidenceStoreProtocol)


# ---------------------------------------------------------------------------
# Protocol surface is read by consumers via duck typing
# ---------------------------------------------------------------------------


def test_protocol_consumer_accepts_fake():
    """Smoke test: a function type-hinted against the Protocol accepts the fake."""

    def consume(store: EvidenceStoreProtocol) -> int:
        store.add("q1", "a1", True)
        store.add("q2", "a2", False)
        return len(store)

    fake = _FakeStore()
    assert consume(fake) == 2


def test_protocol_query_returns_neighbours():
    fake = _FakeStore()
    fake.add("q", "a", True)
    fake.add("q2", "a2", False)
    out: list[Neighbour] = fake.query("anything", k=2)
    assert len(out) == 2
    assert all(isinstance(n, Neighbour) for n in out)


# ---------------------------------------------------------------------------
# Concrete store round-trip via the protocol
# ---------------------------------------------------------------------------


def test_concrete_store_roundtrip_through_protocol(tmp_path):
    store: EvidenceStoreProtocol = EvidenceStore(dim=128)
    store.add("Basel III tier 1?", "Common equity 4.5%", True)
    store.add("BCB Resolução?", "Resolução 4.893/2021", True)

    # Cast back to concrete to exercise persistence.
    assert isinstance(store, PersistentEvidenceStoreProtocol)
    p: Path = tmp_path / "store.npz"
    store.save(p)

    loaded = EvidenceStore.load(p)
    assert isinstance(loaded, EvidenceStoreProtocol)
    assert len(loaded) == 2
    out = loaded.query("Basel III", k=1)
    assert len(out) == 1
    assert isinstance(out[0], Neighbour)


# ---------------------------------------------------------------------------
# Negative case: missing required attribute
# ---------------------------------------------------------------------------


def test_object_missing_dim_does_not_satisfy_protocol():
    class _Broken:
        # Has add/query but no dim attribute.
        def __len__(self) -> int:
            return 0

        def add(self, q, a, c, uq_scores=None):  # type: ignore[no-untyped-def]
            pass

        def query(self, q, k=5):  # type: ignore[no-untyped-def]
            return []

    broken = _Broken()
    # Python 3.12+ runtime_checkable Protocols check BOTH methods AND
    # attributes (PEP 544 update). _Broken is missing `dim`, so it
    # correctly fails isinstance. Previous Python versions only checked
    # methods — that documented limitation no longer applies.
    assert not isinstance(broken, EvidenceStoreProtocol)


def test_object_missing_method_does_not_satisfy_protocol():
    class _Missing:
        dim: int = 16
        # No add, no query, no __len__.

    missing = _Missing()
    assert not isinstance(missing, EvidenceStoreProtocol)
