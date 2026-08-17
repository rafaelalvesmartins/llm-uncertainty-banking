# Copyright 2026 Rafael Martins Alves — Apache-2.0
"""Tamper-evident audit trail — hash chain + SQLite persistence (decoupling step 3).

Extracted VERBATIM from server.py. STATEFUL: ``_audit_append`` rebinds the module
scalars ``_AUDIT_SEQ`` / ``_AUDIT_LAST_HASH`` / ``_AUDIT_DB`` under ``_AUDIT_LOCK`` and
computes a SHA-256 chain (BCB 4893 / SR 11-7 tamper-evidence). server.py keeps the
``server.X`` surface working: the shared ``_AUDIT`` deque + ``_AUDIT_LOCK`` and the
non-rebound functions are plain re-exports; the rebound/monkeypatched names
(``_AUDIT_SEQ``, ``_AUDIT_LAST_HASH``, ``_AUDIT_DB``, ``_audit_db``) are delegated LIVE
to this module by a module-attribute proxy in server.py, so routers reading
``server._AUDIT_SEQ`` and the chain tests writing it / monkeypatching ``server._audit_db``
hit this module's globals. The boot-time ``_audit_restore_from_db()`` runs on import here
(i.e. when server.py imports this module), preserving the restore-on-start contract.
"""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from typing import Any

_AUDIT: deque[dict[str, Any]] = deque(maxlen=2000)
# v10 P3 — tamper-evident hash chain over audit entries. BCB 4893 and SR
# 11-7 both expect audit trails to be detectable-tamper, not just append-
# only. Each entry carries (seq, prev_hash, hash) so a verifier can
# replay sha256(prev_hash || canonical_json_of_payload) and detect any
# silent edit. _AUDIT_LAST_HASH survives the deque's maxlen rotation so
# the chain continues correctly even after old entries fall off.
import hashlib as _hashlib_audit  # noqa: E402
import json as _json_audit  # noqa: E402
import os as _os_audit  # noqa: E402
import sqlite3 as _sqlite_audit  # noqa: E402
import threading as _threading_audit  # noqa: E402

_AUDIT_SEQ = 0
_AUDIT_LAST_HASH = "0" * 64  # genesis anchor
_AUDIT_LOCK = _threading_audit.Lock()

# v14 P3 — SQLite persistence for the audit trail (B-NEW-27 fix). The
# deque stays as the fast in-memory cache for verify/replay/explain; the
# DB is the source of truth that survives backend restarts. BCB 4893 5-yr
# retention is then a matter of disk capacity, not process lifetime.
# Tests / CI override via BRIDGE_AUDIT_DB=:memory: to keep state ephemeral.
_AUDIT_DB_PATH = _os_audit.environ.get(
    "BRIDGE_AUDIT_DB",
    str(Path(_os_audit.environ.get("TMP", "/tmp")) / "bridge_audit.db"),
)
_AUDIT_DB: _sqlite_audit.Connection | None = None


def _audit_db() -> _sqlite_audit.Connection:
    """Lazy-init the SQLite connection + schema. Called under _AUDIT_LOCK."""
    global _AUDIT_DB
    if _AUDIT_DB is None:
        _AUDIT_DB = _sqlite_audit.connect(_AUDIT_DB_PATH, check_same_thread=False)
        # WAL: concurrent readers (the /audit/export + /audit/verify?source=disk
        # reads) don't block the writer, and an interrupted write can't corrupt
        # the chain mid-append. Near-free durability hardening; skipped for the
        # in-memory test DB (WAL is a no-op / unsupported there).
        if _AUDIT_DB_PATH != ":memory:":
            try:
                _AUDIT_DB.execute("PRAGMA journal_mode=WAL")
            except _sqlite_audit.Error:
                pass
        _AUDIT_DB.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_entries (
                seq INTEGER PRIMARY KEY,
                ts REAL NOT NULL,
                prev_hash TEXT NOT NULL,
                hash TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        _AUDIT_DB.execute(
            "CREATE INDEX IF NOT EXISTS audit_entries_ts ON audit_entries(ts)"
        )
        _AUDIT_DB.commit()
    return _AUDIT_DB


def _audit_chain_break(rows: list[tuple[int, float, str, str, str]]) -> int | None:
    """Return the seq of the first chain break in disk rows, or None if intact.

    Mirrors the verifier in routers/audit.py: recompute each entry's sha256 and
    confirm prev_hash links to the prior entry's hash. Used at startup to detect
    a persisted store that was corrupted (e.g. by an earlier crash or a bug that
    diverged the chain head). rows are (seq, ts, prev_hash, hash, payload_json),
    ascending by seq.
    """
    prev_expected: str | None = "0" * 64 if rows and rows[0][0] == 1 else None
    for seq, _ts, prev_hash, h, payload_json in rows:
        try:
            payload = _json_audit.loads(payload_json)
        except Exception:
            return seq
        material = _json_audit.dumps(
            {"seq": seq, "prev_hash": prev_hash, **payload},
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        if _hashlib_audit.sha256(material).hexdigest() != h:
            return seq
        if prev_expected is not None and prev_hash != prev_expected:
            return seq
        prev_expected = h
    return None


def _audit_restore_from_db() -> None:
    """Reload the in-memory deque + chain head from the SQLite store.

    Called once at module load so a restarted backend continues the chain
    from the last persisted seq instead of starting over from genesis.

    Self-heal: if the persisted chain is broken (a prior crash/bug left a
    seam), the corrupt DB is quarantined (renamed with a timestamp) and the
    chain restarts from genesis — so a one-time corruption can never
    permanently brick the tamper-evident demo; this only recovers an
    already-inconsistent file.

    At-rest tamper detection: this boot-time validation plus ``/audit/verify
    ?source=disk`` (which re-runs ``_audit_chain_break`` over every persisted
    row on demand) are what catch an out-of-band edit of ``audit_entries``.
    ``/audit/verify`` with the default ``source=memory`` checks only the live
    deque window and is therefore blind to a disk-only tamper — use
    ``source=disk`` for an at-rest integrity check between restarts.
    """
    global _AUDIT_SEQ, _AUDIT_LAST_HASH, _AUDIT_DB
    db = _audit_db()
    # Validate the FULL persisted chain (ascending) before trusting it.
    all_rows = db.execute(
        "SELECT seq, ts, prev_hash, hash, payload_json FROM audit_entries ORDER BY seq ASC"
    ).fetchall()
    break_seq = _audit_chain_break(all_rows)
    if break_seq is not None:
        # Quarantine the corrupt file and start clean. Best-effort: if the
        # rename fails (locked/permissions), drop the table in place instead.
        print(
            f"[audit] persisted chain broken at seq={break_seq} — quarantining "
            f"{_AUDIT_DB_PATH} and restarting chain from genesis.",
            flush=True,
        )
        try:
            db.close()
        except Exception:
            pass
        _AUDIT_DB = None
        try:
            import os as _os_q

            quarantine = f"{_AUDIT_DB_PATH}.corrupt-{int(time.time())}"
            if _os_q.path.exists(_AUDIT_DB_PATH):
                _os_q.replace(_AUDIT_DB_PATH, quarantine)
        except Exception as e:
            print(f"[audit] quarantine rename failed ({e}); dropping rows in place.", flush=True)
            db2 = _audit_db()
            db2.execute("DELETE FROM audit_entries")
            db2.commit()
        # Fresh genesis: empty deque, seq 0, genesis anchor already set above.
        return

    # Chain is intact — bring the last N entries into the deque (deque maxlen
    # caps the working set; older entries stay on disk for /audit replay).
    rows = all_rows[-(_AUDIT.maxlen or 2000):]
    for seq, ts, prev_hash, h, payload_json in rows:
        try:
            payload = _json_audit.loads(payload_json)
        except Exception:
            continue
        payload["seq"] = seq
        payload["prev_hash"] = prev_hash
        payload["hash"] = h
        payload.setdefault("ts", ts)
        _AUDIT.append(payload)
    if all_rows:
        _AUDIT_SEQ = all_rows[-1][0]
        _AUDIT_LAST_HASH = all_rows[-1][3]


def _audit_append(entry: dict[str, Any]) -> dict[str, Any]:
    """Append one audit entry, stamping it with a tamper-evident hash link.

    Each call increments ``_AUDIT_SEQ``, computes
    ``sha256(prev_hash || canonical_json_without_chain_fields)``, attaches
    ``seq`` / ``prev_hash`` / ``hash`` to the entry, and pushes it onto the
    bounded ``_AUDIT`` deque. The chain is intentionally computed BEFORE the
    deque rotation so the window-level chain remains intact even after old
    entries roll off (the ``seq`` numbers reveal the gap).

    Args:
        entry: Free-form audit payload (must be JSON-serialisable). The
            ``seq`` / ``prev_hash`` / ``hash`` keys are reserved and will be
            overwritten by this helper.

    Returns:
        The same entry dict (now mutated with chain fields) so callers can
        keep a reference if they need to expose ``hash`` on the response.
    """
    global _AUDIT_SEQ, _AUDIT_LAST_HASH
    with _AUDIT_LOCK:
        _AUDIT_SEQ += 1
        entry.pop("seq", None)
        entry.pop("prev_hash", None)
        entry.pop("hash", None)
        # Canonical JSON of the payload + seq + prev_hash. sort_keys is the
        # invariant that lets a verifier reproduce the exact bytes; default=str
        # absorbs any stray non-serialisable types (datetime, etc.) without
        # crashing the audit path.
        payload = {"seq": _AUDIT_SEQ, "prev_hash": _AUDIT_LAST_HASH, **entry}
        material = _json_audit.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        digest = _hashlib_audit.sha256(material).hexdigest()
        entry["seq"] = _AUDIT_SEQ
        entry["prev_hash"] = _AUDIT_LAST_HASH
        entry["hash"] = digest
        _AUDIT_LAST_HASH = digest
        _AUDIT.append(entry)
        # v14 P3 — persist to SQLite as well so a backend restart resumes
        # the chain from the last seq instead of starting over. Wrapped in
        # try/except so disk-full / locked-DB never blocks the live request
        # — the in-memory copy is the immediate source of truth; the disk
        # copy is for durability. Persistence failures get logged for ops.
        try:
            db = _audit_db()
            db.execute(
                """
                INSERT OR REPLACE INTO audit_entries
                (seq, ts, prev_hash, hash, payload_json) VALUES (?,?,?,?,?)
                """,
                (
                    _AUDIT_SEQ,
                    float(entry.get("ts") or time.time()),
                    entry["prev_hash"],
                    entry["hash"],
                    _json_audit.dumps(
                        {k: v for k, v in entry.items() if k not in ("seq", "prev_hash", "hash")},
                        default=str,
                    ),
                ),
            )
            db.commit()
        except Exception as e:
            # Best-effort: print to stderr so operator notices, but don't
            # raise — the request path must stay live even if disk fails.
            print(f"[audit] sqlite persist failed (seq={_AUDIT_SEQ}): {e}", flush=True)
        return entry


# v14 P3 — restore the audit chain from SQLite on import. Must happen
# AFTER _AUDIT, _AUDIT_SEQ, _AUDIT_LAST_HASH, _audit_db are all defined
# (above this point). Skipped when BRIDGE_AUDIT_DB=:memory: which creates
# a fresh in-process DB anyway (tests / CI).
try:
    _audit_restore_from_db()
except Exception as _e:
    print(f"[audit] sqlite restore failed (continuing with empty chain): {_e}", flush=True)


__all__ = [
    '_AUDIT',
    '_AUDIT_SEQ',
    '_AUDIT_LAST_HASH',
    '_AUDIT_LOCK',
    '_AUDIT_DB',
    '_AUDIT_DB_PATH',
    '_audit_db',
    '_audit_chain_break',
    '_audit_restore_from_db',
    '_audit_append',
]
