# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""R2 regression (architecture audit 2026-06-14) — at-rest audit tamper detection.

Before the fix, ``/audit/verify`` only re-hashed the in-memory deque, so an
out-of-band edit of the persisted ``audit_entries`` table (a manual SQLite
``UPDATE`` between restarts) went undetected at runtime. ``/audit/verify
?source=disk`` now re-runs the boot-time chain validator over every persisted
row, so an at-rest tamper is caught without a restart.

Run from the project root::

    pytest bridge-ui/backend/test_audit_disk_integrity.py -v
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402

try:
    from backend.routers import audit as audit_router  # noqa: E402
except ImportError:  # module-mode
    from routers import audit as audit_router  # type: ignore[no-redef]  # noqa: E402

# Use the SAME state.audit module object server bound to (see note in
# test_audit_concurrency.py) — re-importing it can yield a divergent second
# instance under pytest, so the monkeypatched _AUDIT_DB_PATH would not be the one
# server.query()/_audit_append actually writes to.
audit_mod = server._audit_state_mod


def _append(n: int) -> None:
    for i in range(n):
        server._audit_append(
            {
                "ts": time.time(),
                "query": f"q{i}",
                "intent": "balance",
                "confidence": 0.8,
                "decision": "FLAG",
                "answer": "ok",
                "channel": "app",
                "customer_id": "disk-test",
            }
        )


@pytest.fixture
def disk_audit(tmp_path, monkeypatch):
    """Point the audit store at a fresh temp SQLite file and isolate chain state."""
    db_path = tmp_path / "audit_disk_test.db"
    saved = (list(audit_mod._AUDIT), audit_mod._AUDIT_SEQ, audit_mod._AUDIT_LAST_HASH, audit_mod._AUDIT_DB)
    monkeypatch.setattr(audit_mod, "_AUDIT_DB_PATH", str(db_path))
    audit_mod._AUDIT_DB = None  # force a reconnect to the temp file
    audit_mod._AUDIT.clear()
    audit_mod._AUDIT_SEQ = 0
    audit_mod._AUDIT_LAST_HASH = "0" * 64
    yield db_path
    # teardown: close the module's connection so Windows can release the file
    try:
        if audit_mod._AUDIT_DB is not None:
            audit_mod._AUDIT_DB.close()
    except Exception:
        pass
    entries, seq, last, db = saved
    audit_mod._AUDIT.clear()
    audit_mod._AUDIT.extend(entries)
    audit_mod._AUDIT_SEQ = seq
    audit_mod._AUDIT_LAST_HASH = last
    audit_mod._AUDIT_DB = db


def test_disk_verify_valid_then_detects_at_rest_tamper(disk_audit) -> None:
    db_path = disk_audit
    _append(5)

    intact = audit_router.audit_verify(source="disk")
    assert intact["source"] == "disk"
    assert intact["checked"] == 5
    assert intact["valid"] is True
    assert intact["first_failure"] is None

    # Out-of-band tamper: edit a persisted payload directly in SQLite, as an
    # attacker with file access (or a buggy migration) would. Close the module's
    # connection first so our write is the one on disk.
    if audit_mod._AUDIT_DB is not None:
        audit_mod._AUDIT_DB.close()
        audit_mod._AUDIT_DB = None
    con = sqlite3.connect(str(db_path))
    con.execute("UPDATE audit_entries SET payload_json = ? WHERE seq = 3", ('{"decision": "PASSTHROUGH", "answer": "tampered"}',))
    con.commit()
    con.close()

    tampered = audit_router.audit_verify(source="disk")
    assert tampered["valid"] is False
    assert tampered["first_failure"]["seq"] == 3

    # The in-memory window is blind to a disk-only edit — documents the gap that
    # source=disk closes (the deque still holds the original entries).
    mem = audit_router.audit_verify(source="memory")
    assert mem["source"] == "memory"
    assert mem["valid"] is True
