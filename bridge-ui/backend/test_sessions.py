# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Sessions — audit grouped by client/conversation (product #2)."""

from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402

try:
    from backend.routers import sessions as sess  # noqa: E402
except ImportError:
    from routers import sessions as sess  # type: ignore[no-redef]  # noqa: E402


def _entry(cid, decision, ts, intent="balance", pii=0, cost=0.05):
    return {
        "customer_id": cid,
        "channel": "whatsapp",
        "decision": decision,
        "pii_count": pii,
        "cost_cents": cost,
        "ts": ts,
        "query": "consulta",
        "intent": intent,
        "confidence": 0.9,
        "seq": int(ts),
    }


def test_sessions_group_audit_by_client(monkeypatch) -> None:
    fake = deque(
        [
            _entry("C001", "PASSTHROUGH", 1.0, "balance"),
            _entry("C001", "FLAG", 2.0, "transfer"),
            _entry("C003-PEP", "ESCALATE", 3.0, "transfer", pii=1, cost=0.0),
        ]
    )
    monkeypatch.setattr(server, "_AUDIT", fake)
    out = sess.build_sessions()
    assert out["n_sessions"] == 2
    assert out["n_events"] == 3
    by_cid = {x["customer_id"]: x for x in out["sessions"]}
    assert by_cid["C001"]["n_events"] == 2
    assert by_cid["C001"]["decisions"] == {"PASSTHROUGH": 1, "FLAG": 1}
    assert by_cid["C003-PEP"]["pii_events"] == 1
    assert by_cid["C003-PEP"]["decisions"]["ESCALATE"] == 1
    # most-recent session first (last_ts desc)
    assert out["sessions"][0]["customer_id"] == "C003-PEP"
    # each session carries the ordered conversation flow
    assert [e["intent"] for e in by_cid["C001"]["events"]] == ["balance", "transfer"]


def test_empty_audit_yields_no_sessions(monkeypatch) -> None:
    monkeypatch.setattr(server, "_AUDIT", deque())
    out = sess.build_sessions()
    assert out["n_sessions"] == 0
    assert out["sessions"] == []
