# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Unit tests for :mod:`lub.challenge.context_autopilot.recall`.

Spec: planning/25_Context_Autopilot_Spec_2026-04-25.md section 1.3.
"""

from __future__ import annotations

import pytest

from lub.challenge.context_autopilot import (
    EjectionLogEntry,
    RecallRiskFlag,
    detect_recall_risk,
)
from lub.challenge.context_autopilot.recall import load_ejection_log
from lub.evidence import EvidenceStore
from lub.ledger import Ledger


def _log(*items: tuple[int, int, str], session_id: str = "S") -> list[EjectionLogEntry]:
    return [
        EjectionLogEntry(
            eject_id=eid,
            session_id=session_id,
            ejected_turn_id=tid,
            text=text,
        )
        for eid, tid, text in items
    ]


def test_detect_recall_risk_returns_none_for_empty_log() -> None:
    store = EvidenceStore()
    out = detect_recall_risk("any text", [], store)
    assert out is None


def test_detect_recall_risk_returns_none_for_empty_text() -> None:
    store = EvidenceStore()
    log = _log((1, 7, "kyc rules"))
    out = detect_recall_risk("", log, store)
    assert out is None


def test_detect_recall_risk_flags_strong_match() -> None:
    store = EvidenceStore()
    log = _log((1, 7, "kyc rules for retail accounts"))
    flag = detect_recall_risk(
        "kyc rules for retail accounts revisited", log, store, similarity_threshold=0.3
    )
    assert flag is not None
    assert isinstance(flag, RecallRiskFlag)
    assert flag.referenced_eject_id == 1
    assert flag.similarity_score >= 0.3


def test_detect_recall_risk_skips_weak_match() -> None:
    store = EvidenceStore()
    log = _log((1, 7, "kyc rules for retail accounts"))
    out = detect_recall_risk(
        "totally unrelated zzz", log, store, similarity_threshold=0.5
    )
    # similarity is well below 0.5 → None
    assert out is None


def test_detect_recall_risk_picks_best_match() -> None:
    store = EvidenceStore()
    log = _log(
        (1, 1, "weak match anything"),
        (2, 2, "kyc rules retail accounts important"),
    )
    flag = detect_recall_risk(
        "kyc rules retail accounts important", log, store
    )
    assert flag is not None
    assert flag.referenced_eject_id == 2


def test_detect_recall_risk_persists_to_ledger() -> None:
    with Ledger(":memory:") as led:
        # Need a context_ejections row for FK constraint.
        led._conn.execute(  # noqa: SLF001
            "INSERT INTO context_ejections"
            " (session_id, ejected_turn_id, ejection_score,"
            "  similarity_term, age_term, usefulness_term,"
            "  threshold_at_eject, ejected_at)"
            " VALUES ('sess', 7, 0.5, 0.2, 0.1, -0.05, 0.1, '2026-04-25')"
        )
        led._conn.commit()  # noqa: SLF001
        eject_id = led._conn.execute(  # noqa: SLF001
            "SELECT id FROM context_ejections"
        ).fetchone()[0]

        store = EvidenceStore()
        log = [
            EjectionLogEntry(
                eject_id=int(eject_id),
                session_id="sess",
                ejected_turn_id=7,
                text="kyc rules retail",
            )
        ]
        flag = detect_recall_risk(
            "kyc rules retail again", log, store,
            ledger=led, persist=True, similarity_threshold=0.3,
        )
        assert flag is not None
        rows = led._conn.execute(  # noqa: SLF001
            "SELECT later_turn_id, referenced_eject_id, similarity_score"
            " FROM context_recall_flags"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][1] == eject_id


def test_detect_recall_risk_does_not_persist_when_persist_false() -> None:
    with Ledger(":memory:") as led:
        store = EvidenceStore()
        log = _log((99, 7, "kyc rules retail"))
        detect_recall_risk(
            "kyc rules retail",
            log,
            store,
            ledger=led,
            persist=False,
            similarity_threshold=0.0,
        )
        rows = led._conn.execute(  # noqa: SLF001
            "SELECT id FROM context_recall_flags"
        ).fetchall()
    assert rows == []


def test_detect_recall_risk_invalid_k() -> None:
    store = EvidenceStore()
    with pytest.raises(ValueError, match="positive"):
        detect_recall_risk("x", _log((1, 1, "y")), store, k=0)


def test_detect_recall_risk_invalid_threshold() -> None:
    store = EvidenceStore()
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        detect_recall_risk("x", _log((1, 1, "y")), store, similarity_threshold=2.0)


def test_detect_recall_risk_accepts_object_with_text_and_turn_id() -> None:
    class _LaterTurn:
        def __init__(self) -> None:
            self.text = "kyc rules retail"
            self.turn_id = 42

    store = EvidenceStore()
    log = _log((1, 7, "kyc rules retail"))
    flag = detect_recall_risk(_LaterTurn(), log, store, similarity_threshold=0.3)
    assert flag is not None
    assert flag.later_turn_id == 42


def test_detect_recall_risk_skips_log_entries_without_text() -> None:
    store = EvidenceStore()
    log = [
        EjectionLogEntry(eject_id=1, session_id="S", ejected_turn_id=1, text=""),
        EjectionLogEntry(
            eject_id=2, session_id="S", ejected_turn_id=2, text="kyc rules retail"
        ),
    ]
    flag = detect_recall_risk("kyc rules retail", log, store, similarity_threshold=0.3)
    assert flag is not None
    assert flag.referenced_eject_id == 2


def test_load_ejection_log_returns_persisted_rows() -> None:
    with Ledger(":memory:") as led:
        led._conn.execute(  # noqa: SLF001
            "INSERT INTO context_ejections"
            " (session_id, ejected_turn_id, ejection_score,"
            "  similarity_term, age_term, usefulness_term,"
            "  threshold_at_eject, ejected_at)"
            " VALUES ('S', 1, 0.5, 0.2, 0.1, -0.05, 0.1, '2026-04-25')"
        )
        led._conn.execute(  # noqa: SLF001
            "INSERT INTO context_ejections"
            " (session_id, ejected_turn_id, ejection_score,"
            "  similarity_term, age_term, usefulness_term,"
            "  threshold_at_eject, ejected_at)"
            " VALUES ('S', 2, 0.5, 0.2, 0.1, -0.05, 0.1, '2026-04-25')"
        )
        led._conn.execute(  # noqa: SLF001
            "INSERT INTO context_ejections"
            " (session_id, ejected_turn_id, ejection_score,"
            "  similarity_term, age_term, usefulness_term,"
            "  threshold_at_eject, ejected_at)"
            " VALUES ('OTHER', 3, 0.5, 0.2, 0.1, -0.05, 0.1, '2026-04-25')"
        )
        led._conn.commit()  # noqa: SLF001
        log = load_ejection_log(led, "S")
    assert len(log) == 2
    assert {e.ejected_turn_id for e in log} == {1, 2}


def test_load_ejection_log_empty_when_session_unknown() -> None:
    with Ledger(":memory:") as led:
        log = load_ejection_log(led, "ghost")
    assert log == []
