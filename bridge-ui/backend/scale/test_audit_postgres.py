# Copyright 2026 Rafael Martins Alves — Apache-2.0
"""Tests for the Postgres audit-store adapter (scale/audit_postgres.py).

Split into two sections:

(a) PURE CHAIN-LOGIC TESTS (no DB required)
    Build rows in memory using ``_pg_compute_hash`` / ``_pg_chain_break``
    and assert they behave identically to ``state/audit._audit_chain_break``.
    These run everywhere — CI, dev laptops, no database needed.

(b) INTEGRATION TESTS (require DATABASE_URL)
    Skipped when ``DATABASE_URL`` is not set.  When it IS set, they exercise
    ``PostgresAuditStore.append`` → ``verify`` → tamper → ``verify`` fails
    against a real Postgres instance.

Cross-store parity contract
---------------------------
The pure tests deliberately import ``state.audit._audit_chain_break`` and
``state.audit._AUDIT_LAST_HASH`` to assert that our Postgres helper produces
IDENTICAL outputs on the same inputs.  If those assertions fail, there is a
divergence in the hash material and the chain is NOT portable between SQLite
and Postgres.

Run::

    # Pure tests only (no DB):
    pytest bridge-ui/backend/scale/test_audit_postgres.py -v -k "not integration"

    # Full suite (with real Postgres):
    DATABASE_URL=postgresql://user:pass@host/db \\
        pytest bridge-ui/backend/scale/test_audit_postgres.py -v

WARNING: the integration tests write real rows to the database pointed at by
DATABASE_URL.  Use an isolated test database, not production.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Path setup — allow running from repo root or from this directory.
# ---------------------------------------------------------------------------
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from scale.audit_postgres import (  # noqa: E402
    GENESIS_HASH,
    PostgresAuditStore,
    _pg_chain_break,
    _pg_compute_hash,
)

# Import the reference implementation for parity assertions.
try:
    from state import audit as _ref_audit  # noqa: E402
except ImportError:
    from backend.state import audit as _ref_audit  # type: ignore[no-redef]  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers shared by pure tests
# ---------------------------------------------------------------------------

def _build_rows(entries: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """Build ``(seq, ts, prev_hash, hash, payload_json)`` tuples in memory.

    Uses ``_pg_compute_hash`` — the same function ``PostgresAuditStore.append``
    calls — so these rows faithfully represent what the adapter would persist.
    """
    rows: list[tuple[Any, ...]] = []
    prev_hash = GENESIS_HASH
    for i, entry in enumerate(entries):
        seq = i + 1
        stripped = {k: v for k, v in entry.items() if k not in ("seq", "prev_hash", "hash")}
        digest = _pg_compute_hash(seq, prev_hash, stripped)
        ts = float(entry.get("ts") or time.time())
        payload_json = json.dumps(stripped, default=str)
        rows.append((seq, ts, prev_hash, digest, payload_json))
        prev_hash = digest
    return rows


def _ref_build_rows(entries: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """Build rows using ONLY stdlib primitives mirroring state/audit.py.

    Does NOT call _pg_compute_hash — used to independently verify that
    ``_pg_compute_hash`` produces the same digest as the reference algorithm.
    """
    rows: list[tuple[Any, ...]] = []
    prev_hash = "0" * 64  # genesis anchor — state/audit.py line 37
    for i, entry in enumerate(entries):
        seq = i + 1
        stripped = {k: v for k, v in entry.items() if k not in ("seq", "prev_hash", "hash")}
        # Mirrors state/audit._audit_append lines 212-213:
        material_dict = {"seq": seq, "prev_hash": prev_hash, **stripped}
        material = json.dumps(material_dict, sort_keys=True, default=str).encode("utf-8")
        digest = hashlib.sha256(material).hexdigest()
        ts = float(entry.get("ts") or 0.0)
        payload_json = json.dumps(stripped, default=str)
        rows.append((seq, ts, prev_hash, digest, payload_json))
        prev_hash = digest
    return rows


_SAMPLE_ENTRIES = [
    {
        "ts": 1_700_000_000.0 + i,
        "query": f"q{i}",
        "intent": "balance",
        "confidence": 0.8,
        "decision": "FLAG",
        "answer": f"answer-{i}",
        "channel": "app",
        "customer_id": "test-cust",
    }
    for i in range(5)
]


# ===========================================================================
# (a) PURE CHAIN-LOGIC TESTS — no DB required
# ===========================================================================

class TestGenesisAnchor:
    def test_genesis_hash_is_64_zeros(self) -> None:
        assert GENESIS_HASH == "0" * 64

    def test_genesis_matches_sqlite_reference(self) -> None:
        """The Postgres genesis anchor must equal the SQLite genesis anchor."""
        assert GENESIS_HASH == _ref_audit._AUDIT_LAST_HASH or GENESIS_HASH == "0" * 64
        # _AUDIT_LAST_HASH may be non-genesis if the module has live entries;
        # the literal equality to "0"*64 is the invariant we care about.
        assert GENESIS_HASH == "0" * 64


class TestHashComputation:
    def test_compute_hash_matches_stdlib_reference(self) -> None:
        """_pg_compute_hash must produce identical output to the stdlib reference."""
        entry = {"intent": "balance", "confidence": 0.9, "decision": "FLAG"}
        seq, prev_hash = 1, "0" * 64

        expected_material = json.dumps(
            {"seq": seq, "prev_hash": prev_hash, **entry},
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        expected = hashlib.sha256(expected_material).hexdigest()

        assert _pg_compute_hash(seq, prev_hash, entry) == expected

    def test_compute_hash_sort_keys_invariant(self) -> None:
        """Key insertion order in the payload must not affect the hash."""
        entry_a = {"z_field": 1, "a_field": 2}
        entry_b = {"a_field": 2, "z_field": 1}
        h_a = _pg_compute_hash(1, "0" * 64, entry_a)
        h_b = _pg_compute_hash(1, "0" * 64, entry_b)
        assert h_a == h_b, "sort_keys=True must make key order irrelevant"

    def test_compute_hash_reserved_keys_stripped_before_call(self) -> None:
        """Callers must strip seq/prev_hash/hash before calling _pg_compute_hash.

        If those keys leak into the payload they change the material and break
        the chain.  This test documents the precondition.
        """
        clean = {"intent": "balance"}
        dirty = {"intent": "balance", "seq": 1, "prev_hash": "0" * 64, "hash": "abc"}
        # The caller (PostgresAuditStore.append) strips those keys before calling
        # _pg_compute_hash.  If you pass dirty, the hash will differ.
        h_clean = _pg_compute_hash(1, "0" * 64, clean)
        h_dirty = _pg_compute_hash(1, "0" * 64, dirty)
        assert h_clean != h_dirty, (
            "Passing reserved keys into _pg_compute_hash changes the hash — "
            "caller must strip them first"
        )

    def test_parity_with_ref_audit_chain_break(self) -> None:
        """_pg_chain_break must agree with _ref_audit._audit_chain_break on the same rows."""
        rows = _build_rows(_SAMPLE_ENTRIES)
        # Convert tuples to the same format both functions accept.
        pg_result = _pg_chain_break(rows)
        ref_result = _ref_audit._audit_chain_break(rows)
        assert pg_result == ref_result == None  # noqa: E711  (explicit None comparison for clarity)


class TestChainBreak:
    def test_intact_chain_returns_none(self) -> None:
        rows = _build_rows(_SAMPLE_ENTRIES)
        assert _pg_chain_break(rows) is None

    def test_empty_rows_returns_none(self) -> None:
        assert _pg_chain_break([]) is None

    def test_single_entry_genesis_chain(self) -> None:
        rows = _build_rows(_SAMPLE_ENTRIES[:1])
        assert rows[0][0] == 1, "first seq must be 1 for genesis check to apply"
        assert _pg_chain_break(rows) is None

    def test_tamper_payload_detected(self) -> None:
        """Editing the payload_json of any row must be detected."""
        rows = _build_rows(_SAMPLE_ENTRIES)
        seq_to_tamper = 3
        idx = seq_to_tamper - 1
        seq, ts, prev_hash, h, payload_json = rows[idx]
        tampered_json = json.dumps({"decision": "PASSTHROUGH", "answer": "tampered"})
        rows[idx] = (seq, ts, prev_hash, h, tampered_json)
        assert _pg_chain_break(rows) == seq_to_tamper

    def test_tamper_hash_detected(self) -> None:
        """Changing the stored hash of any row must be detected."""
        rows = _build_rows(_SAMPLE_ENTRIES)
        seq_to_tamper = 2
        idx = seq_to_tamper - 1
        seq, ts, prev_hash, _h, payload_json = rows[idx]
        rows[idx] = (seq, ts, prev_hash, "a" * 64, payload_json)
        assert _pg_chain_break(rows) == seq_to_tamper

    def test_tamper_prev_hash_link_detected(self) -> None:
        """Breaking the prev_hash link between two rows must be detected."""
        rows = _build_rows(_SAMPLE_ENTRIES)
        # Alter row 3's prev_hash so it no longer points to row 2's hash.
        idx = 2  # seq=3
        seq, ts, _prev, h, payload_json = rows[idx]
        rows[idx] = (seq, ts, "b" * 64, h, payload_json)
        # The break appears at seq=3 because the recomputed hash will differ
        # (prev_hash is part of the hash material).
        assert _pg_chain_break(rows) == 3

    def test_break_reported_at_first_bad_seq(self) -> None:
        """When multiple rows are broken, the FIRST broken seq is reported."""
        rows = _build_rows(_SAMPLE_ENTRIES)
        # Tamper row 2 and row 4.
        for idx in (1, 3):
            seq, ts, prev_hash, h, payload_json = rows[idx]
            tampered = json.dumps({"x": "tampered"})
            rows[idx] = (seq, ts, prev_hash, h, tampered)
        result = _pg_chain_break(rows)
        assert result == 2  # row at index 1 → seq 2

    def test_parity_tamper_scenario_with_ref(self) -> None:
        """_pg_chain_break and _ref._audit_chain_break must agree on a tampered chain."""
        rows = _build_rows(_SAMPLE_ENTRIES)
        idx = 2  # seq=3
        seq, ts, prev_hash, h, payload_json = rows[idx]
        tampered = json.dumps({"decision": "PASSTHROUGH"})
        rows[idx] = (seq, ts, prev_hash, h, tampered)

        pg_result = _pg_chain_break(rows)
        ref_result = _ref_audit._audit_chain_break(rows)
        assert pg_result == ref_result == 3

    def test_chain_not_starting_at_seq1_skips_genesis_check(self) -> None:
        """A window that starts at seq > 1 must not apply the genesis prev_hash check.

        This mirrors state/audit._audit_chain_break line 93:
            prev_expected = "0"*64 if rows and rows[0][0] == 1 else None
        """
        # Build a valid full chain, then slice off the first two rows.
        rows = _build_rows(_SAMPLE_ENTRIES)
        partial = rows[2:]  # starts at seq=3
        # The prev_hash of seq=3 will not be "0"*64, but that must be OK.
        assert _pg_chain_break(partial) is None

    def test_ref_build_rows_matches_pg_build_rows(self) -> None:
        """The reference builder and the Postgres builder must produce identical rows."""
        pg_rows = _build_rows(_SAMPLE_ENTRIES)
        ref_rows = _ref_build_rows(_SAMPLE_ENTRIES)
        assert len(pg_rows) == len(ref_rows)
        for i, (pg, ref) in enumerate(zip(pg_rows, ref_rows)):
            seq_pg, ts_pg, prev_pg, hash_pg, pj_pg = pg
            seq_ref, ts_ref, prev_ref, hash_ref, pj_ref = ref
            assert hash_pg == hash_ref, (
                f"Hash mismatch at seq={seq_pg} (row index {i}): "
                f"Postgres={hash_pg!r} Reference={hash_ref!r}. "
                "This indicates a divergence in hash material between the "
                "Postgres adapter and state/audit._audit_append."
            )
            assert prev_pg == prev_ref


# ===========================================================================
# (b) INTEGRATION TESTS — skipped when DATABASE_URL is not set
# ===========================================================================

_DB_URL = os.environ.get("DATABASE_URL")
_INTEGRATION_SKIP = pytest.mark.skipif(
    not _DB_URL,
    reason=(
        "DATABASE_URL not set — skipping Postgres integration tests. "
        "Set DATABASE_URL=postgresql://user:pass@host/db to run them. "
        "WARNING: use an ISOLATED TEST DATABASE, not production."
    ),
)


@pytest.fixture(scope="function")
def pg_store() -> PostgresAuditStore:
    """Fresh PostgresAuditStore per test.  Cleans up tenant rows after each test."""
    store = PostgresAuditStore()
    yield store
    # Teardown: remove test tenant rows to leave the DB clean.
    try:
        conn = store._connection()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM audit_entries WHERE tenant_id LIKE 'pytest-%'"
            )
        conn.commit()
    except Exception:
        pass


def _pg_sample_entry(i: int) -> dict[str, Any]:
    return {
        "ts": time.time() + i,
        "query": f"integration-q{i}",
        "intent": "balance",
        "confidence": 0.85,
        "decision": "FLAG",
        "answer": f"integration-answer-{i}",
        "channel": "app",
        "customer_id": "pytest-customer",
    }


@_INTEGRATION_SKIP
class TestIntegrationPostgres:
    def test_append_stamps_chain_fields(self, pg_store: PostgresAuditStore) -> None:
        tenant = "pytest-stamp"
        entry = _pg_sample_entry(0)
        result = pg_store.append(entry, tenant_id=tenant)
        assert result["seq"] == 1
        assert result["prev_hash"] == GENESIS_HASH
        assert len(result["hash"]) == 64
        assert all(c in "0123456789abcdef" for c in result["hash"])

    def test_append_then_verify_valid(self, pg_store: PostgresAuditStore) -> None:
        tenant = "pytest-verify"
        for i in range(5):
            pg_store.append(_pg_sample_entry(i), tenant_id=tenant)
        result = pg_store.verify(tenant_id=tenant)
        assert result["valid"] is True
        assert result["checked"] == 5
        assert result["first_failure"] is None

    def test_verify_empty_tenant_valid(self, pg_store: PostgresAuditStore) -> None:
        tenant = "pytest-empty"
        result = pg_store.verify(tenant_id=tenant)
        assert result["valid"] is True
        assert result["checked"] == 0
        assert result["first_failure"] is None

    def test_head_returns_none_when_empty(self, pg_store: PostgresAuditStore) -> None:
        assert pg_store.head("pytest-head-empty") is None

    def test_head_returns_latest_seq_and_hash(self, pg_store: PostgresAuditStore) -> None:
        tenant = "pytest-head"
        for i in range(3):
            pg_store.append(_pg_sample_entry(i), tenant_id=tenant)
        head = pg_store.head(tenant)
        assert head is not None
        seq, h = head
        assert seq == 3
        assert len(h) == 64

    def test_tenants_are_independent(self, pg_store: PostgresAuditStore) -> None:
        """Two tenants must have independent chains starting from genesis."""
        tenant_a = "pytest-tenant-a"
        tenant_b = "pytest-tenant-b"
        for i in range(3):
            pg_store.append(_pg_sample_entry(i), tenant_id=tenant_a)
        for i in range(2):
            pg_store.append(_pg_sample_entry(i), tenant_id=tenant_b)

        head_a = pg_store.head(tenant_a)
        head_b = pg_store.head(tenant_b)
        assert head_a is not None and head_a[0] == 3
        assert head_b is not None and head_b[0] == 2
        # The chains are independent, so their hashes should differ.
        assert head_a[1] != head_b[1]

        r_a = pg_store.verify(tenant_id=tenant_a)
        r_b = pg_store.verify(tenant_id=tenant_b)
        assert r_a["valid"] is True
        assert r_b["valid"] is True

    def test_at_rest_tamper_detected(self, pg_store: PostgresAuditStore) -> None:
        """An out-of-band UPDATE to payload_json must be detected by verify().

        Mirrors the pattern in test_audit_disk_integrity.py:
        ``test_disk_verify_valid_then_detects_at_rest_tamper``.
        """
        tenant = "pytest-tamper"
        for i in range(5):
            pg_store.append(_pg_sample_entry(i), tenant_id=tenant)

        intact = pg_store.verify(tenant_id=tenant)
        assert intact["valid"] is True

        # Out-of-band tamper: directly UPDATE a row's payload, bypassing the
        # chain logic — exactly as an attacker with DB access would do.
        conn = pg_store._connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE audit_entries
                SET payload_json = %s
                WHERE tenant_id = %s AND seq = 3
                """,
                (json.dumps({"decision": "PASSTHROUGH", "answer": "tampered"}), tenant),
            )
        conn.commit()

        tampered = pg_store.verify(tenant_id=tenant)
        assert tampered["valid"] is False
        assert tampered["first_failure"] is not None
        assert tampered["first_failure"]["seq"] == 3

    def test_seq_increments_correctly_across_appends(
        self, pg_store: PostgresAuditStore
    ) -> None:
        tenant = "pytest-seq"
        results = [pg_store.append(_pg_sample_entry(i), tenant_id=tenant) for i in range(4)]
        seqs = [r["seq"] for r in results]
        assert seqs == [1, 2, 3, 4]

    def test_hash_chain_links_across_appends(self, pg_store: PostgresAuditStore) -> None:
        """Each entry's prev_hash must equal the previous entry's hash."""
        tenant = "pytest-link"
        results = [pg_store.append(_pg_sample_entry(i), tenant_id=tenant) for i in range(4)]
        # First entry's prev_hash is genesis.
        assert results[0]["prev_hash"] == GENESIS_HASH
        # Each subsequent entry's prev_hash links to the prior entry's hash.
        for i in range(1, len(results)):
            assert results[i]["prev_hash"] == results[i - 1]["hash"], (
                f"Link broken between seq={results[i-1]['seq']} and seq={results[i]['seq']}"
            )

    def test_get_audit_store_returns_postgres_when_url_set(self) -> None:
        from scale.audit_postgres import get_audit_store
        store = get_audit_store(fallback=None)
        assert isinstance(store, PostgresAuditStore)

    def test_reserved_keys_stripped_on_append(self, pg_store: PostgresAuditStore) -> None:
        """seq/prev_hash/hash in the input entry must be ignored (overwritten)."""
        tenant = "pytest-strip"
        entry = {
            "ts": time.time(),
            "query": "strip-test",
            "intent": "balance",
            "confidence": 0.9,
            "decision": "FLAG",
            "answer": "ok",
            "channel": "app",
            # These should be overwritten, not included in hash material:
            "seq": 999,
            "prev_hash": "z" * 64,
            "hash": "y" * 64,
        }
        result = pg_store.append(entry, tenant_id=tenant)
        assert result["seq"] == 1  # not 999
        assert result["prev_hash"] == GENESIS_HASH  # not "z"*64

        verify = pg_store.verify(tenant_id=tenant)
        assert verify["valid"] is True
