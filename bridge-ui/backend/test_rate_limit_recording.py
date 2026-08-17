# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Regression test: rate-limited ESCALATE short-circuits must be metered + audited.

Companion to ``test_escalate_persistence.py`` (which covers the ``dq_input`` block).
This covers the *other* pre-pipeline short-circuit: when ``_RATE_LIMITER.allow()``
returns ``False`` the handler ``return``\\s a HTTP 200 ``decision="ESCALATE"`` via
``_record_short_circuit``. Without that recording call the rate-limited caller —
exactly the kind of event a governance console must show (SR 11-7 / BCB 4.893) —
never incremented ``queries_total`` / ``decisions.ESCALATE`` and never extended the
tamper-evident audit hash-chain.

The echoed response query must be PII-masked (LGPD Art. 46 / BCB 4.893 §6), so we
send a query carrying a CPF and assert the clear-text CPF is gone from the response.

Run from the project root::

    pytest bridge-ui/backend/test_rate_limit_recording.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402  — must follow sys.path setup

_client = TestClient(server.app)

# CPF embedded in the query — the short-circuit response must echo it masked.
_CPF = "123.456.789-00"
_QUERY_WITH_CPF = f"What is the balance for CPF {_CPF}?"


def _state() -> tuple[int, int, int]:
    """Snapshot (queries_total, ESCALATE count, audit chain head)."""
    m = server._METRICS
    return (m.queries_total, dict(m.decisions).get("ESCALATE", 0), server._AUDIT_SEQ)


def test_rate_limited_escalate_is_metered_and_audited(monkeypatch) -> None:
    """A rate-limited (ESCALATE) query must advance metrics AND the audit chain."""
    # Force the limiter to reject so we deterministically hit the short-circuit.
    monkeypatch.setattr(server._RATE_LIMITER, "allow", lambda *a, **k: False)

    q0, e0, a0 = _state()

    r = _client.post(
        "/query",
        json={"query": _QUERY_WITH_CPF, "customer_id": "demo-customer", "channel": "app"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "ESCALATE"
    assert body["intent"] == "rate_limited"

    q1, e1, a1 = _state()
    assert q1 == q0 + 1, f"queries_total did not increment for a rate-limit ESCALATE ({q0}->{q1})"
    assert e1 == e0 + 1, f"decisions.ESCALATE did not increment ({e0}->{e1})"
    assert a1 == a0 + 1, f"audit chain head did not advance for a rate-limit ESCALATE ({a0}->{a1})"


def test_rate_limited_response_query_is_masked(monkeypatch) -> None:
    """The echoed response query must be PII-masked (no clear-text CPF)."""
    monkeypatch.setattr(server._RATE_LIMITER, "allow", lambda *a, **k: False)

    r = _client.post(
        "/query",
        json={"query": _QUERY_WITH_CPF, "customer_id": "demo-customer", "channel": "app"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert _CPF not in body["query"], f"clear-text CPF leaked in the rate-limit response: {body['query']!r}"
