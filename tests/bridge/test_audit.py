# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :mod:`lub.bridge.audit`.

The audit trail is the regulatory backbone of Bridge — every test in
this file pins behavior that BCB 4893, BCBS 239, or SR 11-7 reviewers
would look at: durable writes, immutable entries, queryable by customer
and period, no silent drops when a banking decision is logged.
"""

from __future__ import annotations

import csv
import io
import json
import threading
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from lub.connectors.bridge import (
    AgentResponse,
    AgentRole,
    BridgeResult,
    EscalationReason,
)
from lub.connectors.bridge.audit import (
    AuditDecision,
    AuditEntry,
    AuditTrail,
    AuditTrailError,
    _as_utc,
    _decision_label,
    _entry_from_result,
    _normalize_period,
    _period_tag,
)
from lub.guard import GuardResult, PolicyDecision, PolicyOutcome
from lub.types import UncertaintyResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_uncertainty_result(answer: str = "Seu saldo é R$ 1.250,00.", confidence: float = 0.92) -> UncertaintyResult:
    return UncertaintyResult(
        answer=answer,
        confidence=confidence,
        raw_scores={"entropy": 0.1},
        should_refuse=False,
    )


def _make_outcome(
    decision: PolicyDecision = PolicyDecision.PASSTHROUGH,
    confidence: float = 0.92,
    threshold: float = 0.7,
    answer: str | None = "Seu saldo é R$ 1.250,00.",
) -> PolicyOutcome:
    return PolicyOutcome(
        decision=decision,
        confidence=confidence,
        threshold=threshold,
        passed=(decision == PolicyDecision.PASSTHROUGH),
        answer=answer,
        reason="",
    )


def _make_guard_result(
    decision: PolicyDecision = PolicyDecision.PASSTHROUGH,
    confidence: float = 0.92,
    threshold: float = 0.7,
    answer: str = "Seu saldo é R$ 1.250,00.",
) -> GuardResult:
    return GuardResult(
        raw=_make_uncertainty_result(answer=answer, confidence=confidence),
        outcome=_make_outcome(
            decision=decision,
            confidence=confidence,
            threshold=threshold,
            answer=answer,
        ),
        output=answer,
        rmf_subcategory="GOVERN 3.2",
    )


def _make_bridge_result(
    *,
    role: AgentRole = AgentRole.CHATBOT,
    prompt: str = "Qual meu saldo?",
    answer: str = "Seu saldo é R$ 1.250,00.",
    decision: PolicyDecision = PolicyDecision.PASSTHROUGH,
    confidence: float = 0.92,
    escalated: bool = False,
    escalation_reason: EscalationReason | None = None,
    with_guard: bool = True,
) -> BridgeResult:
    verdict = (
        _make_guard_result(decision=decision, confidence=confidence, answer=answer)
        if with_guard
        else None
    )
    return BridgeResult(
        primary=AgentResponse(
            role=role,
            prompt=prompt,
            answer=answer,
            guard_result=verdict,
        ),
        escalated=escalated,
        escalation_reason=escalation_reason,
    )


@pytest.fixture
def trail_path(tmp_path: Path) -> Path:
    return tmp_path / "bridge_audit.jsonl"


@pytest.fixture
def trail(trail_path: Path) -> AuditTrail:
    """Disk-backed trail with fsync disabled for speed."""
    t = AuditTrail(trail_path, fsync=False)
    yield t
    t.close()


@pytest.fixture
def memory_trail() -> AuditTrail:
    """Memory-only trail — no JSONL file."""
    t = AuditTrail(None)
    yield t
    t.close()


def _entry(**overrides) -> AuditEntry:
    defaults = dict(
        customer_id="cust_h_001",
        session_id="sess_abc",
        query="Qual meu saldo?",
        response="Seu saldo é R$ 1.250,00.",
        confidence=0.92,
        decision=AuditDecision.PASSTHROUGH,
        agent_used=AgentRole.CHATBOT.value,
        model_used="gpt-4.1-azure",
        latency_ms=120.5,
    )
    defaults.update(overrides)
    return AuditEntry(**defaults)


# ---------------------------------------------------------------------------
# AuditDecision
# ---------------------------------------------------------------------------


class TestAuditDecision:
    def test_values_includes_policy_decisions_plus_escalate_and_unknown(self) -> None:
        assert AuditDecision.values() == frozenset(
            {"passthrough", "flag", "abstain", "raise", "escalate", "unknown"}
        )

    def test_constants_match_string_values(self) -> None:
        assert AuditDecision.PASSTHROUGH == "passthrough"
        assert AuditDecision.FLAG == "flag"
        assert AuditDecision.ABSTAIN == "abstain"
        assert AuditDecision.RAISE == "raise"
        assert AuditDecision.ESCALATE == "escalate"
        assert AuditDecision.UNKNOWN == "unknown"

    def test_every_policy_decision_value_is_a_legal_audit_decision(self) -> None:
        for pd in PolicyDecision:
            if pd == PolicyDecision.REASK:
                # REASK is an internal control-flow decision, never surfaces in audit
                continue
            assert pd.value in AuditDecision.values()


# ---------------------------------------------------------------------------
# AuditEntry — construction, validation, immutability
# ---------------------------------------------------------------------------


class TestAuditEntryBasics:
    def test_minimum_fields_construct(self) -> None:
        e = _entry()
        assert e.customer_id == "cust_h_001"
        assert e.decision == "passthrough"
        assert e.entry_id  # auto-generated
        assert e.timestamp.tzinfo is not None

    def test_entry_id_is_unique_per_construction(self) -> None:
        a = _entry()
        b = _entry()
        assert a.entry_id != b.entry_id

    def test_entry_is_frozen(self) -> None:
        e = _entry()
        with pytest.raises(ValidationError):
            e.customer_id = "tampered"  # type: ignore[misc]

    def test_extra_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AuditEntry(
                customer_id="x",
                session_id="y",
                query="q",
                response="r",
                decision=AuditDecision.PASSTHROUGH,
                agent_used="chatbot",
                model_used="m",
                rogue_field="hacker",  # type: ignore[call-arg]
            )

    def test_unknown_decision_raises(self) -> None:
        with pytest.raises(ValidationError) as exc:
            _entry(decision="approved")
        assert "decision must be one of" in str(exc.value)

    @pytest.mark.parametrize(
        "decision",
        ["passthrough", "flag", "abstain", "raise", "escalate", "unknown"],
    )
    def test_each_legal_decision_accepted(self, decision: str) -> None:
        e = _entry(decision=decision)
        assert e.decision == decision


class TestAuditEntryConfidenceValidator:
    def test_clamps_above_one(self) -> None:
        e = _entry(confidence=1.7)
        assert e.confidence == 1.0

    def test_clamps_below_zero(self) -> None:
        e = _entry(confidence=-0.4)
        assert e.confidence == 0.0

    def test_nan_becomes_none(self) -> None:
        e = _entry(confidence=float("nan"))
        assert e.confidence is None

    def test_none_stays_none(self) -> None:
        e = _entry(confidence=None)
        assert e.confidence is None

    def test_in_range_value_unchanged(self) -> None:
        e = _entry(confidence=0.42)
        assert e.confidence == pytest.approx(0.42)


class TestAuditEntryLatencyValidator:
    def test_negative_becomes_zero(self) -> None:
        e = _entry(latency_ms=-5.0)
        assert e.latency_ms == 0.0

    def test_nan_becomes_zero(self) -> None:
        e = _entry(latency_ms=float("nan"))
        assert e.latency_ms == 0.0

    def test_positive_unchanged(self) -> None:
        e = _entry(latency_ms=88.25)
        assert e.latency_ms == pytest.approx(88.25)


class TestAuditEntrySerialization:
    def test_to_json_round_trips_via_model_validate(self) -> None:
        e = _entry(extra={"intent": "balance", "channel": "whatsapp"})
        payload = json.loads(e.to_json())
        rebuilt = AuditEntry.model_validate(payload)
        assert rebuilt.entry_id == e.entry_id
        assert rebuilt.extra == {"intent": "balance", "channel": "whatsapp"}

    def test_to_row_keys_match_csv_columns(self) -> None:
        e = _entry()
        row = e.to_row()
        # CSV header order is contractual — verify presence of every column.
        expected = {
            "entry_id",
            "timestamp",
            "customer_id",
            "session_id",
            "agent_used",
            "model_used",
            "decision",
            "confidence",
            "latency_ms",
            "escalated",
            "escalation_reason",
            "query",
            "response",
            "extra",
        }
        assert set(row.keys()) == expected

    def test_to_row_formats_confidence_with_six_decimals(self) -> None:
        e = _entry(confidence=0.5)
        assert e.to_row()["confidence"] == "0.500000"

    def test_to_row_confidence_none_serializes_as_empty(self) -> None:
        e = _entry(confidence=None)
        assert e.to_row()["confidence"] == ""

    def test_to_row_escalated_boolean_as_lowercase_string(self) -> None:
        assert _entry(escalated=False).to_row()["escalated"] == "false"
        assert _entry(escalated=True).to_row()["escalated"] == "true"

    def test_to_row_extra_json_encoded(self) -> None:
        e = _entry(extra={"intent": "transfer"})
        assert json.loads(e.to_row()["extra"]) == {"intent": "transfer"}

    def test_to_row_empty_extra_renders_empty_string(self) -> None:
        assert _entry().to_row()["extra"] == ""


# ---------------------------------------------------------------------------
# AuditTrail — construction and lifecycle
# ---------------------------------------------------------------------------


class TestAuditTrailInit:
    def test_memory_only_trail_initializes(self) -> None:
        t = AuditTrail(None)
        assert len(t) == 0
        t.close()

    def test_disk_trail_creates_parent_dir(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "deep" / "audit.jsonl"
        t = AuditTrail(target)
        assert target.parent.exists()
        t.close()

    def test_init_replays_existing_file(self, tmp_path: Path) -> None:
        p = tmp_path / "audit.jsonl"
        e1 = _entry(customer_id="c1")
        e2 = _entry(customer_id="c2")
        p.write_text(e1.to_json() + "\n" + e2.to_json() + "\n", encoding="utf-8")
        t = AuditTrail(p)
        try:
            assert len(t) == 2
            assert {e.customer_id for e in t.all_entries()} == {"c1", "c2"}
        finally:
            t.close()

    def test_replay_tolerates_malformed_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "audit.jsonl"
        good = _entry(customer_id="c1")
        p.write_text(
            good.to_json() + "\n" + "this is not json\n" + '{"only":"bad"}\n',
            encoding="utf-8",
        )
        t = AuditTrail(p)
        try:
            # Bad rows skipped; good row replays.
            assert len(t) == 1
            assert t.all_entries()[0].customer_id == "c1"
        finally:
            t.close()

    def test_replay_skips_blank_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "audit.jsonl"
        good = _entry()
        p.write_text("\n\n" + good.to_json() + "\n\n", encoding="utf-8")
        t = AuditTrail(p)
        try:
            assert len(t) == 1
        finally:
            t.close()

    def test_open_failure_raises_audit_trail_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Force Path.mkdir to fail so __init__ enters the OSError branch.
        def boom(self: Path, **kwargs: object) -> None:
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "mkdir", boom)
        with pytest.raises(AuditTrailError, match="unable to open audit trail"):
            AuditTrail(tmp_path / "x.jsonl")


class TestAuditTrailLifecycle:
    def test_context_manager_closes_handle(self, trail_path: Path) -> None:
        with AuditTrail(trail_path) as t:
            t.log_decision(_entry())
        # After close, writing must refuse.
        with pytest.raises(AuditTrailError, match="audit trail is closed"):
            t.log_decision(_entry())

    def test_close_is_idempotent(self, trail_path: Path) -> None:
        t = AuditTrail(trail_path)
        t.close()
        t.close()  # must not raise

    def test_len_reflects_logged_entries(self, memory_trail: AuditTrail) -> None:
        assert len(memory_trail) == 0
        memory_trail.log_decision(_entry())
        memory_trail.log_decision(_entry())
        assert len(memory_trail) == 2


# ---------------------------------------------------------------------------
# AuditTrail — log_decision
# ---------------------------------------------------------------------------


class TestLogDecision:
    def test_writes_one_line_per_entry(self, trail: AuditTrail, trail_path: Path) -> None:
        e1 = _entry(customer_id="c1")
        e2 = _entry(customer_id="c2")
        trail.log_decision(e1)
        trail.log_decision(e2)
        trail.close()  # flush

        lines = trail_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["customer_id"] == "c1"
        assert json.loads(lines[1])["customer_id"] == "c2"

    def test_returns_same_entry_object(self, memory_trail: AuditTrail) -> None:
        e = _entry()
        assert memory_trail.log_decision(e) is e

    def test_rejects_non_entry(self, memory_trail: AuditTrail) -> None:
        with pytest.raises(TypeError, match="requires an AuditEntry"):
            memory_trail.log_decision({"not": "an entry"})  # type: ignore[arg-type]

    def test_memory_only_logs_without_disk(self, memory_trail: AuditTrail) -> None:
        e = _entry()
        memory_trail.log_decision(e)
        assert memory_trail.all_entries() == (e,)

    def test_log_after_close_raises(self, trail: AuditTrail) -> None:
        trail.close()
        with pytest.raises(AuditTrailError, match="closed"):
            trail.log_decision(_entry())

    def test_write_oserror_raises_audit_trail_error(
        self,
        trail: AuditTrail,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Replace the open file handle with one that errors on write.
        class _BadFile:
            def write(self, _data: str) -> None:
                raise OSError("disk full")

            def flush(self) -> None:
                pass

            def fileno(self) -> int:
                return -1

            def close(self) -> None:
                pass

        monkeypatch.setattr(trail, "_file", _BadFile())
        with pytest.raises(AuditTrailError, match="failed to persist"):
            trail.log_decision(_entry())


# ---------------------------------------------------------------------------
# AuditTrail — log_bridge_result
# ---------------------------------------------------------------------------


class TestLogBridgeResult:
    def test_extracts_query_response_and_role(self, memory_trail: AuditTrail) -> None:
        result = _make_bridge_result(prompt="Qual meu saldo?", answer="R$ 1.250,00")
        entry = memory_trail.log_bridge_result(
            result,
            customer_id="cust_42",
            session_id="sess_42",
            model_used="gpt-4.1-azure",
            latency_ms=110.0,
        )
        assert entry.query == "Qual meu saldo?"
        assert entry.response == "R$ 1.250,00"
        assert entry.agent_used == AgentRole.CHATBOT.value
        assert entry.model_used == "gpt-4.1-azure"
        assert entry.confidence == pytest.approx(0.92)
        assert entry.decision == AuditDecision.PASSTHROUGH
        assert entry.escalated is False
        assert entry.escalation_reason is None

    def test_records_escalation_reason(self, memory_trail: AuditTrail) -> None:
        result = _make_bridge_result(
            decision=PolicyDecision.ABSTAIN,
            confidence=0.21,
            escalated=True,
            escalation_reason=EscalationReason.POLICY_ABSTAIN,
        )
        entry = memory_trail.log_bridge_result(
            result,
            customer_id="cust_42",
            session_id="sess_42",
            model_used="claude-opus-4-7",
            latency_ms=350.0,
        )
        assert entry.escalated is True
        assert entry.escalation_reason == "policy_abstain"
        assert entry.decision == AuditDecision.ABSTAIN

    def test_extra_metadata_propagates(self, memory_trail: AuditTrail) -> None:
        result = _make_bridge_result()
        entry = memory_trail.log_bridge_result(
            result,
            customer_id="c",
            session_id="s",
            model_used="m",
            latency_ms=10.0,
            extra={"intent": "balance", "channel": "whatsapp"},
        )
        assert entry.extra == {"intent": "balance", "channel": "whatsapp"}

    def test_missing_guard_produces_unknown_decision(self, memory_trail: AuditTrail) -> None:
        # Bridge dispatched but the guard threw — primary.guard_result is None
        # and platform did not escalate (corner case: agent-error path without
        # the escalated flag, exercised here directly to pin _decision_label).
        result = _make_bridge_result(with_guard=False, escalated=False)
        entry = memory_trail.log_bridge_result(
            result,
            customer_id="c",
            session_id="s",
            model_used="m",
            latency_ms=10.0,
        )
        assert entry.confidence is None
        assert entry.decision == AuditDecision.UNKNOWN

    def test_escalated_without_verdict_records_escalate(self, memory_trail: AuditTrail) -> None:
        result = _make_bridge_result(
            with_guard=False,
            escalated=True,
            escalation_reason=EscalationReason.AGENT_ERROR,
        )
        entry = memory_trail.log_bridge_result(
            result,
            customer_id="c",
            session_id="s",
            model_used="m",
            latency_ms=10.0,
        )
        assert entry.decision == AuditDecision.ESCALATE
        assert entry.escalation_reason == "agent_error"


# ---------------------------------------------------------------------------
# AuditTrail — queries
# ---------------------------------------------------------------------------


class TestQueries:
    def test_query_trail_filters_by_customer(self, memory_trail: AuditTrail) -> None:
        memory_trail.log_decision(_entry(customer_id="alice"))
        memory_trail.log_decision(_entry(customer_id="bob"))
        memory_trail.log_decision(_entry(customer_id="alice"))

        alice = memory_trail.query_trail("alice")
        assert len(alice) == 2
        assert all(e.customer_id == "alice" for e in alice)

    def test_query_trail_unknown_customer_returns_empty(self, memory_trail: AuditTrail) -> None:
        memory_trail.log_decision(_entry(customer_id="alice"))
        assert memory_trail.query_trail("ghost") == []

    @pytest.mark.parametrize("bad", ["", None, 123, []])
    def test_query_trail_rejects_non_string_or_empty(self, memory_trail: AuditTrail, bad: object) -> None:
        memory_trail.log_decision(_entry(customer_id="alice"))
        assert memory_trail.query_trail(bad) == []  # type: ignore[arg-type]

    def test_query_by_session(self, memory_trail: AuditTrail) -> None:
        memory_trail.log_decision(_entry(session_id="s1"))
        memory_trail.log_decision(_entry(session_id="s2"))
        memory_trail.log_decision(_entry(session_id="s1"))
        assert len(memory_trail.query_by_session("s1")) == 2
        assert memory_trail.query_by_session("") == []

    def test_query_by_period_half_open_interval(self, memory_trail: AuditTrail) -> None:
        now = datetime.now(UTC)
        old = _entry(timestamp=now - timedelta(hours=2))
        mid = _entry(timestamp=now - timedelta(minutes=30))
        new = _entry(timestamp=now + timedelta(minutes=10))
        memory_trail.log_decision(old)
        memory_trail.log_decision(mid)
        memory_trail.log_decision(new)

        window = memory_trail.query_by_period(now - timedelta(hours=1), now)
        ids = {e.entry_id for e in window}
        assert mid.entry_id in ids
        assert old.entry_id not in ids
        assert new.entry_id not in ids

    def test_query_by_period_treats_naive_as_utc(self, memory_trail: AuditTrail) -> None:
        now = datetime.now(UTC)
        e = _entry(timestamp=now)
        memory_trail.log_decision(e)
        naive_start = (now - timedelta(minutes=5)).replace(tzinfo=None)
        naive_end = (now + timedelta(minutes=5)).replace(tzinfo=None)
        window = memory_trail.query_by_period(naive_start, naive_end)
        assert e.entry_id in {x.entry_id for x in window}

    def test_query_by_period_inverted_raises(self, memory_trail: AuditTrail) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="precedes start"):
            memory_trail.query_by_period(now, now - timedelta(hours=1))

    def test_all_entries_is_immutable_snapshot(self, memory_trail: AuditTrail) -> None:
        memory_trail.log_decision(_entry())
        snap = memory_trail.all_entries()
        assert isinstance(snap, tuple)
        memory_trail.log_decision(_entry())
        # Older snapshot must not pick up the new write.
        assert len(snap) == 1


# ---------------------------------------------------------------------------
# AuditTrail — CSV export
# ---------------------------------------------------------------------------


class TestExportCSV:
    def test_export_creates_file_with_header(self, trail: AuditTrail, tmp_path: Path) -> None:
        now = datetime.now(UTC)
        trail.log_decision(_entry(timestamp=now))
        out = trail.export_csv(
            (now - timedelta(minutes=1), now + timedelta(minutes=1)),
            output_dir=tmp_path / "exports",
        )
        assert out.exists()
        with out.open(encoding="utf-8") as fp:
            reader = csv.DictReader(fp)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["agent_used"] == AgentRole.CHATBOT.value
        assert rows[0]["decision"] == AuditDecision.PASSTHROUGH

    def test_export_default_filename_includes_period(self, trail: AuditTrail, tmp_path: Path) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 2, tzinfo=UTC)
        out = trail.export_csv((start, end), output_dir=tmp_path / "out")
        assert "20260101T000000Z" in out.name
        assert "20260102T000000Z" in out.name
        assert out.name.endswith(".csv")

    def test_export_explicit_filename(self, trail: AuditTrail, tmp_path: Path) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 2, tzinfo=UTC)
        out = trail.export_csv((start, end), output_dir=tmp_path / "out", filename="report.csv")
        assert out.name == "report.csv"

    def test_export_period_filters_rows(self, trail: AuditTrail, tmp_path: Path) -> None:
        now = datetime.now(UTC)
        trail.log_decision(_entry(customer_id="in", timestamp=now))
        trail.log_decision(_entry(customer_id="out", timestamp=now - timedelta(hours=10)))
        out = trail.export_csv(
            (now - timedelta(minutes=5), now + timedelta(minutes=5)),
            output_dir=tmp_path / "exports",
        )
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        ids = {r["customer_id"] for r in rows}
        assert ids == {"in"}

    def test_export_memory_trail_falls_back_to_cwd(
        self,
        memory_trail: AuditTrail,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        memory_trail.log_decision(_entry())
        now = datetime.now(UTC)
        out = memory_trail.export_csv(
            (now - timedelta(hours=1), now + timedelta(hours=1)),
        )
        assert out.parent == tmp_path
        assert out.exists()

    def test_export_inverted_period_raises(self, memory_trail: AuditTrail, tmp_path: Path) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="precedes start"):
            memory_trail.export_csv((now, now - timedelta(hours=1)), output_dir=tmp_path)

    def test_export_write_failure_raises_audit_trail_error(
        self,
        memory_trail: AuditTrail,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        memory_trail.log_decision(_entry())
        now = datetime.now(UTC)

        def boom(*_a: object, **_kw: object) -> io.StringIO:
            raise OSError("disk full")

        monkeypatch.setattr(Path, "open", boom)
        with pytest.raises(AuditTrailError, match="failed to write audit CSV"):
            memory_trail.export_csv(
                (now - timedelta(hours=1), now + timedelta(hours=1)),
                output_dir=tmp_path,
            )


# ---------------------------------------------------------------------------
# Banking intent scenarios — what the regulator actually wants to read
# ---------------------------------------------------------------------------


class TestBankingIntents:
    @pytest.mark.parametrize(
        ("prompt", "answer", "intent"),
        [
            ("Qual meu saldo?", "Seu saldo é R$ 1.250,00.", "balance"),
            ("Quero transferir 500 para Joao", "Transferência agendada.", "transfer"),
            ("pagar 150 reais pro Joao via PIX", "PIX agendado.", "pix"),
            ("Não recebi meu cartão!", "Lamento. Vou registrar.", "complaint"),
        ],
    )
    def test_each_intent_audited(
        self,
        memory_trail: AuditTrail,
        prompt: str,
        answer: str,
        intent: str,
    ) -> None:
        result = _make_bridge_result(prompt=prompt, answer=answer)
        entry = memory_trail.log_bridge_result(
            result,
            customer_id="cust_1",
            session_id="sess_1",
            model_used="gpt-4.1-azure",
            latency_ms=80.0,
            extra={"intent": intent},
        )
        assert entry.query == prompt
        assert entry.response == answer
        assert entry.extra["intent"] == intent

    def test_low_confidence_escalates_and_records(self, memory_trail: AuditTrail) -> None:
        # Below 0.7 threshold — guard ABSTAINs and platform escalates.
        result = _make_bridge_result(
            prompt="quanto rende minha poupança em comparação com a Selic ajustada?",
            answer="",
            decision=PolicyDecision.ABSTAIN,
            confidence=0.18,
            escalated=True,
            escalation_reason=EscalationReason.POLICY_ABSTAIN,
        )
        entry = memory_trail.log_bridge_result(
            result,
            customer_id="cust_low",
            session_id="sess_low",
            model_used="gpt-4.1-azure",
            latency_ms=300.0,
        )
        assert entry.escalated is True
        assert entry.decision == AuditDecision.ABSTAIN
        assert entry.confidence == pytest.approx(0.18)

    def test_high_confidence_passes_through(self, memory_trail: AuditTrail) -> None:
        result = _make_bridge_result(
            prompt="Qual meu saldo?",
            answer="R$ 1.250,00",
            decision=PolicyDecision.PASSTHROUGH,
            confidence=0.97,
        )
        entry = memory_trail.log_bridge_result(
            result,
            customer_id="cust_high",
            session_id="sess_high",
            model_used="gpt-4.1-azure",
            latency_ms=80.0,
        )
        assert entry.escalated is False
        assert entry.decision == AuditDecision.PASSTHROUGH

    def test_flag_decision_records_flag(self, memory_trail: AuditTrail) -> None:
        result = _make_bridge_result(
            decision=PolicyDecision.FLAG,
            confidence=0.55,
            escalated=True,
            escalation_reason=EscalationReason.POLICY_FLAG,
        )
        entry = memory_trail.log_bridge_result(
            result,
            customer_id="cust_flag",
            session_id="sess_flag",
            model_used="gpt-4.1-azure",
            latency_ms=120.0,
        )
        assert entry.decision == AuditDecision.FLAG
        assert entry.escalation_reason == "policy_flag"

    def test_unknown_role_escalation_logged(self, memory_trail: AuditTrail) -> None:
        # BridgePlatform.dispatch on unregistered role: empty answer, no guard.
        result = BridgeResult(
            primary=AgentResponse(
                role=AgentRole.SMART_PAYMENTS,
                prompt="pagar 150 reais pro Joao",
                answer="",
                guard_result=None,
            ),
            escalated=True,
            escalation_reason=EscalationReason.UNKNOWN_ROLE,
        )
        entry = memory_trail.log_bridge_result(
            result,
            customer_id="cust_x",
            session_id="sess_x",
            model_used="gpt-4.1-azure",
            latency_ms=2.0,
        )
        assert entry.escalated is True
        assert entry.decision == AuditDecision.ESCALATE
        assert entry.agent_used == "smart_payments"
        assert entry.response == ""


# ---------------------------------------------------------------------------
# Edge cases — empty input, PII, large values
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_query_and_response_still_recorded(self, memory_trail: AuditTrail) -> None:
        entry = _entry(query="", response="")
        memory_trail.log_decision(entry)
        assert memory_trail.all_entries()[0].query == ""

    def test_response_carries_raw_cpf_string_unchanged(self, memory_trail: AuditTrail) -> None:
        # The audit module is not a PII filter — that lives upstream. But it
        # must record whatever the platform produced verbatim so post-hoc
        # compliance scans can detect leaks.
        entry = _entry(response="CPF: 123.456.789-00 confirmado.")
        memory_trail.log_decision(entry)
        round_tripped = json.loads(memory_trail.all_entries()[0].to_json())
        assert "123.456.789-00" in round_tripped["response"]

    def test_extra_with_compliance_flags_persists(self, memory_trail: AuditTrail) -> None:
        entry = _entry(
            extra={
                "cpf_detected": True,
                "prohibited_phrase": False,
                "channel": "whatsapp",
            }
        )
        memory_trail.log_decision(entry)
        loaded = memory_trail.all_entries()[0]
        assert loaded.extra["cpf_detected"] is True

    def test_very_long_query_truncation_is_callers_problem(self, memory_trail: AuditTrail) -> None:
        long = "a" * 50_000
        memory_trail.log_decision(_entry(query=long))
        assert len(memory_trail.all_entries()[0].query) == 50_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_decision_label_passthrough(self) -> None:
        result = _make_bridge_result(decision=PolicyDecision.PASSTHROUGH)
        verdict = result.primary.guard_result
        assert _decision_label(result, verdict) == AuditDecision.PASSTHROUGH

    def test_decision_label_abstain(self) -> None:
        result = _make_bridge_result(decision=PolicyDecision.ABSTAIN, escalated=True)
        verdict = result.primary.guard_result
        assert _decision_label(result, verdict) == AuditDecision.ABSTAIN

    def test_decision_label_no_verdict_no_escalation_is_unknown(self) -> None:
        result = _make_bridge_result(with_guard=False, escalated=False)
        assert _decision_label(result, None) == AuditDecision.UNKNOWN

    def test_decision_label_no_verdict_but_escalated_is_escalate(self) -> None:
        result = _make_bridge_result(
            with_guard=False,
            escalated=True,
            escalation_reason=EscalationReason.AGENT_ERROR,
        )
        assert _decision_label(result, None) == AuditDecision.ESCALATE

    def test_entry_from_result_tolerates_unconvertible_confidence(self) -> None:
        # An estimator that emits a non-numeric confidence (e.g., a sentinel
        # object during a misconfiguration) must not crash the audit path —
        # the entry is still produced, just with confidence=None.
        class _BadFloat:
            def __float__(self) -> float:
                raise TypeError("not a number")

        raw = UncertaintyResult(
            answer="x",
            confidence=0.5,
            raw_scores={},
            should_refuse=False,
        )
        # Bypass the dataclass's __init__ validator with object.__setattr__
        # (frozen dataclass) to inject a hostile confidence value.
        object.__setattr__(raw, "confidence", _BadFloat())
        outcome = _make_outcome()
        verdict = GuardResult(raw=raw, outcome=outcome, output="x", rmf_subcategory="GOVERN 3.2")
        result = BridgeResult(
            primary=AgentResponse(
                role=AgentRole.CHATBOT,
                prompt="p",
                answer="x",
                guard_result=verdict,
            )
        )
        entry = _entry_from_result(
            result=result,
            customer_id="c",
            session_id="s",
            model_used="m",
            latency_ms=1.0,
            extra=None,
        )
        assert entry.confidence is None

    def test_normalize_period_accepts_naive_as_utc(self) -> None:
        s, e = _normalize_period(datetime(2026, 1, 1), datetime(2026, 1, 2))
        assert s.tzinfo == UTC
        assert e.tzinfo == UTC

    def test_normalize_period_converts_non_utc_tz(self) -> None:
        sao_paulo = timezone(timedelta(hours=-3))
        s, e = _normalize_period(
            datetime(2026, 1, 1, 12, tzinfo=sao_paulo),
            datetime(2026, 1, 1, 13, tzinfo=sao_paulo),
        )
        assert s.tzinfo == UTC
        assert s.hour == 15  # 12:00-03:00 == 15:00 UTC

    def test_normalize_period_rejects_inverted(self) -> None:
        with pytest.raises(ValueError, match="precedes start"):
            _normalize_period(datetime(2026, 1, 2, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC))

    def test_as_utc_passes_through_aware_utc(self) -> None:
        dt = datetime(2026, 1, 1, tzinfo=UTC)
        assert _as_utc(dt) is dt or _as_utc(dt) == dt

    def test_period_tag_format(self) -> None:
        assert _period_tag(datetime(2026, 5, 12, 9, 30, 45, tzinfo=UTC)) == "20260512T093045Z"


# ---------------------------------------------------------------------------
# Concurrency — the trail is shared across BridgePlatform threads
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_concurrent_writes_do_not_lose_entries(self, trail: AuditTrail) -> None:
        N = 20
        WORKERS = 8

        def worker(tag: str) -> None:
            for i in range(N):
                trail.log_decision(_entry(customer_id=f"{tag}-{i}"))

        threads = [threading.Thread(target=worker, args=(f"t{w}",)) for w in range(WORKERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(trail) == N * WORKERS
        ids = {e.customer_id for e in trail.all_entries()}
        assert len(ids) == N * WORKERS
