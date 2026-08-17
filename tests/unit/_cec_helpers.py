# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Shared helpers for CEC unit tests.

Hermetic fixture loader for the JSONL ledger seed at
``tests/fixtures/cec_ledger.jsonl``. The seed file mirrors a subset of
production-shaped rows with explicit ``created_at`` timestamps so the
window-based queries in :mod:`lub.challenge.replay` exercise their
filter clauses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lub.evidence import EvidenceStore
from lub.ledger import Ledger

_FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "cec_ledger.jsonl"


def load_ledger_fixture(path: str = ":memory:") -> Ledger:
    """Build an in-memory ledger seeded from the JSONL fixture.

    Each fixture row supplies a complete (query → answer → score →
    policy → outcome) chain. The ``created_at`` ISO-string is written
    directly into the row so the engine's window filter can be tested
    against deterministic timestamps.
    """
    led = Ledger(path)
    rows = _read_jsonl(_FIXTURE_PATH)
    conn = led._conn  # noqa: SLF001
    for r in rows:
        cur = conn.execute(
            "INSERT INTO queries (prompt_hash, prompt, domain, created_at)"
            " VALUES (?, ?, ?, ?)",
            (
                Ledger._hash_prompt(r["prompt"]),
                r["prompt"],
                r.get("domain", "generic"),
                r["created_at"],
            ),
        )
        qid = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO answers (query_id, model, backend, tier, answer, cost, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                qid,
                r["model"],
                r["backend"],
                r.get("tier"),
                r["answer"],
                float(r.get("cost", 0.0)),
                r["created_at"],
            ),
        )
        aid = cur.lastrowid
        if r.get("confidence") is not None:
            conn.execute(
                "INSERT INTO uq_scores (answer_id, method, value) VALUES (?, ?, ?)",
                (aid, "confidence", float(r["confidence"])),
            )
        if r.get("decision") is not None:
            conn.execute(
                "INSERT INTO policy_decisions (answer_id, decision, threshold, passed, reason)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    aid,
                    r["decision"],
                    float(r.get("threshold", 0.85)),
                    int(r.get("passed", 1)),
                    "fixture",
                ),
            )
        if r.get("correct") is not None:
            conn.execute(
                "INSERT INTO outcomes (answer_id, ground_truth, correct)"
                " VALUES (?, ?, ?)",
                (aid, r.get("ground_truth"), int(r["correct"])),
            )
    conn.commit()
    return led


def attach_drift_events(
    ledger: Ledger,
    events: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Attach a ``drift_events`` dict to the ledger for CEC tests.

    The CEC drift-reasoning resolver looks at ``ledger.drift_events`` as
    one of its supported lookup sources. The mapping is intentionally
    duck-typed (no strong schema requirement) so tests can keep it
    lightweight.
    """
    payload = events or {
        "drift-2026-04-15": {
            "psi": 0.32,
            "reference_mean": 0.88,
            "current_mean": 0.74,
            "domain": "regulatory-qa",
            "detected_at": "2026-04-15T13:30:00",
            "query_text": "regulatory-qa drift moderate-to-significant",
        },
        "drift-2026-04-20": {
            "psi": 0.12,
            "reference_mean": 0.85,
            "current_mean": 0.87,
            "domain": "regulatory-qa",
            "detected_at": "2026-04-20T15:30:00",
            "query_text": "regulatory-qa drift moderate",
        },
    }
    ledger.drift_events = payload  # type: ignore[attr-defined]
    return payload


def deterministic_evidence_store() -> EvidenceStore:
    """Return an EvidenceStore seeded with a few hash-embedded rows.

    Uses :class:`lub.evidence.EvidenceStore` with the default hashed
    TF embedding — deterministic, no torch / faiss required.
    """
    store = EvidenceStore()
    seeds = [
        ("regulatory-qa drift fall in confidence", "abstain", False),
        ("regulatory-qa drift moderate distribution shift", "PASS", True),
        ("regulatory-qa stable confidence operating window", "PASS", True),
        ("Basel III calibration drift event", "abstain", False),
        ("BCB resolution domain shift", "PASS", True),
    ]
    for q, a, ok in seeds:
        store.add(question=q, answer=a, correct=ok)
    return store


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


__all__ = [
    "attach_drift_events",
    "deterministic_evidence_store",
    "load_ledger_fixture",
]
