# Copyright 2026 Rafael Martins Alves — Apache-2.0
"""Postgres audit-store adapter for Track D (scale layer).

WARNING — SECURITY-CRITICAL / NOT YET VALIDATED
================================================
This module implements a tamper-evident SHA-256 hash chain for a banking
audit trail (BCB 4893 / SR 11-7).  The chain logic here was transcribed
VERBATIM from ``state/audit.py`` (``_audit_append`` lines 183-248 and
``_audit_chain_break`` lines 84-109).  A single divergence in the hash
material (key order, encoding, field set) silently breaks cross-store
portability and the tamper-evidence guarantee.

BEFORE THIS MODULE CAN BE TRUSTED IN PRODUCTION you MUST:
  1. Run ``test_audit_postgres.py`` against a real Postgres instance
     (set DATABASE_URL=postgresql://... and run pytest).
  2. Manually cross-check portability: write N entries via ``state/audit.py``
     (SQLite), export their (seq, prev_hash, hash, payload_json) rows, feed
     them into ``_pg_chain_break`` (copied here), and confirm zero breaks.
  3. Run the existing ``test_audit_disk_integrity.py`` suite — it must still
     pass unchanged.
  4. Have a second engineer independently trace ``_pg_compute_hash`` against
     ``state/audit._audit_append`` line-by-line and sign off.

ADDITIVE + FLAG-GATED: nothing in this module is wired into the running
demo.  The only entry point for the rest of the application is
``get_audit_store(fallback)`` which returns the Postgres store ONLY when
``DATABASE_URL`` is set in the environment, otherwise returns ``fallback``
unchanged.  See docs/SCALE_WIRING.md for the wiring plan.

Dependencies: ``psycopg[binary]>=3.1`` (requirements-scale.txt).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any

# ---------------------------------------------------------------------------
# Hash-chain helpers — must match state/audit.py EXACTLY
# ---------------------------------------------------------------------------

_GENESIS_HASH: str = "0" * 64  # mirrors state/audit.py line 37


def _pg_compute_hash(seq: int, prev_hash: str, payload: dict[str, Any]) -> str:
    """Compute the chain hash for one entry.

    Mirrors ``state/audit._audit_append`` lines 212-214::

        payload = {"seq": _AUDIT_SEQ, "prev_hash": _AUDIT_LAST_HASH, **entry}
        material = _json_audit.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        digest = _hashlib_audit.sha256(material).hexdigest()

    ``payload`` here is the *stripped* entry (no seq/prev_hash/hash keys),
    matching what ``_audit_append`` receives after popping those keys at
    lines 205-207.
    """
    material_dict = {"seq": seq, "prev_hash": prev_hash, **payload}
    material = json.dumps(material_dict, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _pg_chain_break(rows: list[tuple[int, float, str, str, str]]) -> int | None:
    """Return the seq of the first chain break, or None if intact.

    Copied verbatim from ``state/audit._audit_chain_break`` (lines 84-109).
    Rows are ``(seq, ts, prev_hash, hash, payload_json)`` ascending by seq.

    This copy exists so the Postgres adapter does NOT import from state/audit
    (which triggers SQLite setup + boot-time restore on import) and so the
    verifier logic here is self-contained and auditable alongside this file.
    Any future change to ``state/audit._audit_chain_break`` MUST be mirrored
    here and the cross-store tests re-run.
    """
    prev_expected: str | None = _GENESIS_HASH if rows and rows[0][0] == 1 else None
    for seq, _ts, prev_hash, h, payload_json in rows:
        try:
            payload = json.loads(payload_json)
        except Exception:
            return seq
        material = json.dumps(
            {"seq": seq, "prev_hash": prev_hash, **payload},
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        if hashlib.sha256(material).hexdigest() != h:
            return seq
        if prev_expected is not None and prev_hash != prev_expected:
            return seq
        prev_expected = h
    return None


# ---------------------------------------------------------------------------
# PostgresAuditStore
# ---------------------------------------------------------------------------

class PostgresAuditStore:
    """Tamper-evident audit store backed by Postgres.

    Each tenant has its own independent hash chain (genesis + head). Within
    this process each tenant's chain is serialised by a per-tenant
    threading.Lock. NOTE: cross-process serialisation is NOT yet implemented —
    a Postgres advisory lock (or `SELECT ... FOR UPDATE` on the tenant head)
    MUST be added before running >1 worker/replica, or concurrent appends can
    fork a tenant chain. Treat as single-process until then (docs/SCALE_WIRING.md).

    Schema (bootstrapped lazily on first use)::

        CREATE TABLE IF NOT EXISTS audit_entries (
            tenant_id    TEXT    NOT NULL,
            seq          INTEGER NOT NULL,
            ts           DOUBLE PRECISION NOT NULL,
            prev_hash    TEXT    NOT NULL,
            hash         TEXT    NOT NULL,
            payload_json TEXT    NOT NULL,
            PRIMARY KEY (tenant_id, seq)
        );

    The ``tenant_id`` + ``seq`` pair is the primary key so each tenant's
    chain is a contiguous 1-based sequence independent of other tenants.

    Usage::

        store = PostgresAuditStore()          # lazy connect
        store.append({"query": "..."}, tenant_id="bank-a")
        result = store.verify(tenant_id="bank-a")   # {"valid": True, ...}
        head   = store.head("bank-a")               # (seq, hash) | None

    Do NOT instantiate directly in production without first completing the
    validation steps described in this module's docstring.
    """

    def __init__(self) -> None:
        self._conn: Any = None          # psycopg.Connection, lazy
        self._connect_lock = threading.Lock()
        # Per-tenant in-process chain state: (seq, last_hash).
        # Populated from the DB on first use per tenant.
        self._tenant_state: dict[str, tuple[int, str]] = {}
        self._tenant_locks: dict[str, threading.Lock] = {}
        self._tenant_meta_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connection(self) -> Any:
        """Return (and lazily create) the psycopg connection.

        Reads DATABASE_URL from the environment.  Raises RuntimeError if
        DATABASE_URL is not set — callers (get_audit_store) guard against
        this, but a direct instantiation must also fail loudly.
        """
        if self._conn is not None:
            return self._conn
        with self._connect_lock:
            if self._conn is not None:
                return self._conn
            url = os.environ.get("DATABASE_URL")
            if not url:
                raise RuntimeError(
                    "PostgresAuditStore: DATABASE_URL is not set. "
                    "Use get_audit_store(fallback) to select the store safely."
                )
            import psycopg
            self._conn = psycopg.connect(url, autocommit=False)
            self._bootstrap_schema()
            return self._conn

    def _bootstrap_schema(self) -> None:
        """Create the audit_entries table + index if they do not exist."""
        conn = self._conn
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_entries (
                    tenant_id    TEXT             NOT NULL,
                    seq          INTEGER          NOT NULL,
                    ts           DOUBLE PRECISION NOT NULL,
                    prev_hash    TEXT             NOT NULL,
                    hash         TEXT             NOT NULL,
                    payload_json TEXT             NOT NULL,
                    PRIMARY KEY (tenant_id, seq)
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS audit_entries_tenant_ts
                    ON audit_entries (tenant_id, ts)
                """
            )
        conn.commit()

    def _tenant_lock(self, tenant_id: str) -> threading.Lock:
        """Return (creating if needed) the per-tenant threading lock."""
        with self._tenant_meta_lock:
            if tenant_id not in self._tenant_locks:
                self._tenant_locks[tenant_id] = threading.Lock()
            return self._tenant_locks[tenant_id]

    def _load_tenant_head(self, tenant_id: str) -> tuple[int, str]:
        """Read the current chain head for *tenant_id* from Postgres.

        Returns ``(seq, last_hash)``.  Returns ``(0, GENESIS_HASH)`` if no
        rows exist yet (fresh tenant chain).  Must be called under the
        per-tenant lock.
        """
        conn = self._connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT seq, hash
                FROM audit_entries
                WHERE tenant_id = %s
                ORDER BY seq DESC
                LIMIT 1
                """,
                (tenant_id,),
            )
            row = cur.fetchone()
        if row is None:
            return (0, _GENESIS_HASH)
        return (int(row[0]), str(row[1]))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(self, entry: dict[str, Any], *, tenant_id: str) -> dict[str, Any]:
        """Append one audit entry to the tenant's hash chain.

        Computes prev_hash/hash IDENTICALLY to ``state/audit._audit_append``
        (lines 183-248).  Strips any pre-existing ``seq``, ``prev_hash``,
        ``hash`` keys from *entry* before hashing (same as lines 205-207).

        Args:
            entry:     Free-form audit payload (JSON-serialisable).  The
                       ``seq`` / ``prev_hash`` / ``hash`` keys are reserved
                       and will be overwritten.
            tenant_id: Logical tenant identifier.  Each tenant has its own
                       independent 1-based chain.

        Returns:
            The same *entry* dict mutated with ``seq``, ``prev_hash``,
            ``hash`` set — mirrors the return contract of ``_audit_append``.
        """
        lock = self._tenant_lock(tenant_id)
        with lock:
            # Load current head from DB (authoritative across processes).
            seq, last_hash = self._load_tenant_head(tenant_id)

            # Strip reserved chain fields — mirrors state/audit.py lines 205-207.
            entry.pop("seq", None)
            entry.pop("prev_hash", None)
            entry.pop("hash", None)

            next_seq = seq + 1
            prev_hash = last_hash

            # Compute hash — mirrors state/audit.py lines 212-214.
            digest = _pg_compute_hash(next_seq, prev_hash, entry)

            # Payload stored WITHOUT chain fields — mirrors state/audit.py
            # lines 236-240 (the dict comprehension that excludes seq/prev_hash/hash).
            payload_json = json.dumps(
                {k: v for k, v in entry.items() if k not in ("seq", "prev_hash", "hash")},
                default=str,
            )

            ts_value = float(entry.get("ts") or time.time())

            conn = self._connection()
            try:
                with conn.cursor() as cur:
                    # Append-only: plain INSERT. A duplicate (tenant_id, seq)
                    # raises UniqueViolation (caught below) instead of silently
                    # overwriting a prior row — overwriting would destroy the
                    # tamper-evidence guarantee.
                    cur.execute(
                        """
                        INSERT INTO audit_entries
                            (tenant_id, seq, ts, prev_hash, hash, payload_json)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (tenant_id, next_seq, ts_value, prev_hash, digest, payload_json),
                    )
                conn.commit()
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise RuntimeError(
                    f"PostgresAuditStore.append failed for tenant={tenant_id!r} "
                    f"seq={next_seq}: {exc}"
                ) from exc

            # Stamp the entry in-place — mirrors state/audit.py lines 215-218.
            entry["seq"] = next_seq
            entry["prev_hash"] = prev_hash
            entry["hash"] = digest
            return entry

    def verify(self, *, tenant_id: str) -> dict[str, Any]:
        """Re-validate the full persisted chain for *tenant_id*.

        Runs the same algorithm as ``_audit_chain_break`` (state/audit.py
        lines 84-109) — copied as ``_pg_chain_break`` in this module so the
        verifier is self-contained and auditable without importing state/audit.

        Returns::

            {
                "valid": bool,
                "tenant_id": str,
                "checked": int,        # number of rows verified
                "head_seq": int,
                "head_hash": str,
                "first_failure": None | {"seq": int, "reason": str},
            }
        """
        conn = self._connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT seq, ts, prev_hash, hash, payload_json
                FROM audit_entries
                WHERE tenant_id = %s
                ORDER BY seq ASC
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()

        break_seq = _pg_chain_break(list(rows))
        head_seq = int(rows[-1][0]) if rows else 0
        head_hash = str(rows[-1][3]) if rows else _GENESIS_HASH

        return {
            "valid": break_seq is None,
            "tenant_id": tenant_id,
            "checked": len(rows),
            "head_seq": head_seq,
            "head_hash": head_hash,
            "first_failure": (
                None
                if break_seq is None
                else {
                    "seq": break_seq,
                    "reason": (
                        "chain broken at this seq — recomputed sha256 != stored hash, "
                        "or prev_hash does not link to the previous entry"
                    ),
                }
            ),
        }

    def head(self, tenant_id: str) -> tuple[int, str] | None:
        """Return ``(seq, hash)`` of the latest entry for *tenant_id*, or None.

        None means no entries have been appended for this tenant yet.
        """
        conn = self._connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT seq, hash
                FROM audit_entries
                WHERE tenant_id = %s
                ORDER BY seq DESC
                LIMIT 1
                """,
                (tenant_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return (int(row[0]), str(row[1]))


# ---------------------------------------------------------------------------
# Factory — the ONLY wiring point for the rest of the application
# ---------------------------------------------------------------------------

def get_audit_store(fallback: Any) -> Any:
    """Return a ``PostgresAuditStore`` iff ``DATABASE_URL`` is set, else *fallback*.

    This is the ONLY entry point callers outside this module should use.
    It is intentionally not wired anywhere in the running demo.

    Usage (future wiring — see docs/SCALE_WIRING.md)::

        from scale.audit_postgres import get_audit_store
        from state import audit as _sqlite_audit

        AUDIT_STORE = get_audit_store(fallback=_sqlite_audit)

    Args:
        fallback: Returned unchanged when ``DATABASE_URL`` is not set.  Must
                  be the existing ``state/audit`` module (or any object whose
                  ``_audit_append`` / ``_audit_chain_break`` are trustworthy).

    Returns:
        Either a ``PostgresAuditStore`` instance or *fallback*.
    """
    if os.environ.get("DATABASE_URL"):
        return PostgresAuditStore()
    return fallback


__all__ = [
    "GENESIS_HASH",
    "PostgresAuditStore",
    "get_audit_store",
    # Exposed for cross-store validation in tests:
    "_pg_compute_hash",
    "_pg_chain_break",
]

# Public alias so callers can reference the genesis constant without the
# leading underscore.
GENESIS_HASH = _GENESIS_HASH
