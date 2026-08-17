# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :mod:`lub.bridge.analytics`.

Bradesco's Azure AI Foundry case study publishes two headline KPIs the
behavioural analytics engine must reproduce: **90% retention** and
**83% end-to-end resolution**. These tests pin the funnel arithmetic,
the histogram binning, the hour-of-day workload profile, and the
ledger's refusal to crash on malformed telemetry — exactly the
behaviour BCB 4893, BCBS 239, and SR 11-7 reviewers look at.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

import pytest

from lub.connectors.bridge import AgentResponse, AgentRole, BridgeResult, EscalationReason
from lub.connectors.bridge.analytics import (
    DEFAULT_HISTOGRAM_BINS,
    DEFAULT_LEDGER_CAPACITY,
    DEFAULT_RESOLUTION_TARGET,
    DEFAULT_RETENTION_TARGET,
    AnalyticsEvent,
    BridgeAnalytics,
    ConfidenceBucket,
    FunnelReport,
    HourStats,
    Period,
    _channel_label,
    _ensure_iterable,
    _intent_label,
)
from lub.connectors.bridge.session import Channel
from lub.guard import GuardResult, PolicyDecision, PolicyOutcome
from lub.types import UncertaintyResult

# ---------------------------------------------------------------------------
# Fixtures and builders
# ---------------------------------------------------------------------------


def _uncertainty(confidence: float = 0.92, answer: str = "Seu saldo é R$ 1.250,00.") -> UncertaintyResult:
    return UncertaintyResult(
        answer=answer,
        confidence=confidence,
        raw_scores={"entropy": 0.1},
        should_refuse=False,
    )


def _outcome(
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


def _guard_result(
    decision: PolicyDecision = PolicyDecision.PASSTHROUGH,
    confidence: float = 0.92,
    answer: str = "Seu saldo é R$ 1.250,00.",
) -> GuardResult:
    return GuardResult(
        raw=_uncertainty(confidence=confidence, answer=answer),
        outcome=_outcome(decision=decision, confidence=confidence, answer=answer),
        output=answer,
        rmf_subcategory="GOVERN 3.2",
    )


def _bridge_result(
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
        _guard_result(decision=decision, confidence=confidence, answer=answer)
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
def engine() -> BridgeAnalytics:
    return BridgeAnalytics()


@pytest.fixture
def small_engine() -> BridgeAnalytics:
    """Engine with a tiny capacity to exercise eviction."""
    return BridgeAnalytics(capacity=3)


def _ts(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_retention_target_matches_bradesco_published_value(self) -> None:
        assert DEFAULT_RETENTION_TARGET == 0.90

    def test_resolution_target_matches_bradesco_published_value(self) -> None:
        assert DEFAULT_RESOLUTION_TARGET == 0.83

    def test_default_capacity_is_positive(self) -> None:
        assert DEFAULT_LEDGER_CAPACITY > 0

    def test_default_histogram_bins_is_ten(self) -> None:
        assert DEFAULT_HISTOGRAM_BINS == 10


# ---------------------------------------------------------------------------
# Period
# ---------------------------------------------------------------------------


class TestPeriod:
    def test_duration_returns_end_minus_start(self) -> None:
        p = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 8))
        assert p.duration == timedelta(days=7)

    def test_end_before_start_raises(self) -> None:
        with pytest.raises(ValueError, match="precedes start"):
            Period(start=_ts(2026, 1, 8), end=_ts(2026, 1, 1))

    def test_equal_start_and_end_is_allowed(self) -> None:
        p = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 1))
        assert p.duration == timedelta(0)

    def test_contains_includes_start(self) -> None:
        p = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 8))
        assert p.contains(_ts(2026, 1, 1)) is True

    def test_contains_excludes_end(self) -> None:
        p = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 8))
        assert p.contains(_ts(2026, 1, 8)) is False

    def test_contains_interior_point(self) -> None:
        p = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 8))
        assert p.contains(_ts(2026, 1, 4, 6, 30)) is True

    def test_shift_translates_window(self) -> None:
        p = Period(start=_ts(2026, 1, 8), end=_ts(2026, 1, 15))
        shifted = p.shift(-p.duration)
        assert shifted.start == _ts(2026, 1, 1)
        assert shifted.end == _ts(2026, 1, 8)

    def test_to_dict_emits_isoformat(self) -> None:
        p = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 8))
        out = p.to_dict()
        assert out == {
            "start": _ts(2026, 1, 1).isoformat(),
            "end": _ts(2026, 1, 8).isoformat(),
        }

    def test_period_is_hashable(self) -> None:
        p = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 8))
        assert hash(p) == hash(Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 8)))


# ---------------------------------------------------------------------------
# AnalyticsEvent
# ---------------------------------------------------------------------------


class TestAnalyticsEvent:
    def test_basic_construction(self) -> None:
        ev = AnalyticsEvent(
            timestamp=_ts(2026, 1, 10),
            customer_id="cust_001",
            role=AgentRole.CHATBOT,
            channel="whatsapp",
            intent="balance",
            escalated=False,
            escalation_reason=None,
            decision=PolicyDecision.PASSTHROUGH,
            confidence=0.9,
            latency_ms=120.0,
        )
        assert ev.customer_id == "cust_001"
        assert ev.intent == "balance"

    def test_frozen(self) -> None:
        ev = AnalyticsEvent(
            timestamp=_ts(2026, 1, 10),
            customer_id="cust_001",
            role=AgentRole.CHATBOT,
            channel="whatsapp",
            intent="balance",
            escalated=False,
            escalation_reason=None,
            decision=None,
            confidence=None,
            latency_ms=10.0,
        )
        with pytest.raises(Exception):
            ev.customer_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Value-object serialization
# ---------------------------------------------------------------------------


class TestFunnelReportSerialization:
    def _report(self, **overrides) -> FunnelReport:
        period = Period(start=_ts(2026, 1, 8), end=_ts(2026, 1, 15))
        defaults = dict(
            period=period,
            prior_period=period.shift(-period.duration),
            new_customers=2,
            active_customers=5,
            retained_customers=4,
            churned_customers=1,
            queries_total=10,
            queries_resolved=9,
            retention_rate=0.95,
            resolution_rate=0.90,
        )
        defaults.update(overrides)
        return FunnelReport(**defaults)

    def test_meets_retention_default(self) -> None:
        assert self._report(retention_rate=0.91).meets_retention_target()

    def test_misses_retention_default(self) -> None:
        assert not self._report(retention_rate=0.50).meets_retention_target()

    def test_meets_retention_custom_target(self) -> None:
        assert self._report(retention_rate=0.70).meets_retention_target(target=0.60)

    def test_meets_resolution_default(self) -> None:
        assert self._report(resolution_rate=0.84).meets_resolution_target()

    def test_misses_resolution_default(self) -> None:
        assert not self._report(resolution_rate=0.50).meets_resolution_target()

    def test_to_dict_emits_all_required_keys(self) -> None:
        d = self._report().to_dict()
        required = {
            "period",
            "prior_period",
            "new_customers",
            "active_customers",
            "retained_customers",
            "churned_customers",
            "queries_total",
            "queries_resolved",
            "retention_rate",
            "resolution_rate",
            "meets_retention_target",
            "meets_resolution_target",
        }
        assert required.issubset(d.keys())

    def test_to_dict_period_serialized(self) -> None:
        d = self._report().to_dict()
        assert "start" in d["period"]
        assert "end" in d["period"]


class TestConfidenceBucketSerialization:
    def test_to_dict_round_trip(self) -> None:
        b = ConfidenceBucket(lower=0.5, upper=0.6, count=3, share=0.25)
        assert b.to_dict() == {
            "lower": 0.5,
            "upper": 0.6,
            "count": 3,
            "share": 0.25,
        }


class TestHourStatsSerialization:
    def test_to_dict_round_trip(self) -> None:
        h = HourStats(
            hour=14,
            query_count=42,
            escalation_count=4,
            escalation_rate=4 / 42,
            avg_latency_ms=120.5,
        )
        out = h.to_dict()
        assert out["hour"] == 14
        assert out["query_count"] == 42
        assert out["escalation_count"] == 4
        assert out["avg_latency_ms"] == pytest.approx(120.5)


# ---------------------------------------------------------------------------
# BridgeAnalytics construction
# ---------------------------------------------------------------------------


class TestBridgeAnalyticsInit:
    def test_default_targets(self) -> None:
        a = BridgeAnalytics()
        assert a.retention_target == DEFAULT_RETENTION_TARGET
        assert a.resolution_target == DEFAULT_RESOLUTION_TARGET
        assert len(a) == 0

    def test_negative_capacity_rejected(self) -> None:
        with pytest.raises(ValueError, match="capacity"):
            BridgeAnalytics(capacity=-1)

    def test_retention_target_above_one_rejected(self) -> None:
        with pytest.raises(ValueError, match="retention_target"):
            BridgeAnalytics(retention_target=1.5)

    def test_retention_target_below_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="retention_target"):
            BridgeAnalytics(retention_target=-0.01)

    def test_resolution_target_out_of_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="resolution_target"):
            BridgeAnalytics(resolution_target=2.0)

    def test_capacity_zero_disables_cap(self) -> None:
        a = BridgeAnalytics(capacity=0)
        for i in range(50):
            a.record_event(
                AnalyticsEvent(
                    timestamp=_ts(2026, 1, 1, 0, i),
                    customer_id=f"c{i}",
                    role=AgentRole.CHATBOT,
                    channel="whatsapp",
                    intent="balance",
                    escalated=False,
                    escalation_reason=None,
                    decision=None,
                    confidence=None,
                    latency_ms=10.0,
                )
            )
        assert len(a) == 50

    def test_custom_targets_round_trip_through_properties(self) -> None:
        a = BridgeAnalytics(retention_target=0.75, resolution_target=0.65)
        assert a.retention_target == 0.75
        assert a.resolution_target == 0.65


# ---------------------------------------------------------------------------
# record_query
# ---------------------------------------------------------------------------


class TestRecordQuery:
    def test_records_balance_query(self, engine: BridgeAnalytics) -> None:
        engine.record_query(
            _bridge_result(prompt="Qual meu saldo?"),
            customer_id="cust_001",
            latency_ms=120.0,
            channel=Channel.WHATSAPP,
            intent="balance",
            timestamp=_ts(2026, 1, 10),
        )
        assert len(engine) == 1
        (ev,) = engine.snapshot_events()
        assert ev.customer_id == "cust_001"
        assert ev.channel == "whatsapp"
        assert ev.intent == "balance"
        assert ev.role == AgentRole.CHATBOT
        assert ev.decision == PolicyDecision.PASSTHROUGH
        assert ev.confidence == pytest.approx(0.92)
        assert ev.escalated is False
        assert ev.latency_ms == 120.0

    def test_records_transfer_intent(self, engine: BridgeAnalytics) -> None:
        engine.record_query(
            _bridge_result(prompt="Quero fazer um TED de R$ 500"),
            customer_id="cust_002",
            latency_ms=210.0,
            channel=Channel.MOBILE_APP,
            intent="transfer",
        )
        (ev,) = engine.snapshot_events()
        assert ev.intent == "transfer"
        assert ev.channel == "mobile_app"

    def test_records_pix_intent(self, engine: BridgeAnalytics) -> None:
        engine.record_query(
            _bridge_result(prompt="pagar 150 reais pro Joao"),
            customer_id="cust_003",
            latency_ms=180.0,
            channel=Channel.WHATSAPP,
            intent="pix",
        )
        (ev,) = engine.snapshot_events()
        assert ev.intent == "pix"

    def test_records_complaint_intent(self, engine: BridgeAnalytics) -> None:
        engine.record_query(
            _bridge_result(
                prompt="Quero abrir uma reclamação",
                decision=PolicyDecision.FLAG,
                escalated=True,
                escalation_reason=EscalationReason.POLICY_FLAG,
            ),
            customer_id="cust_004",
            latency_ms=300.0,
            channel=Channel.CALL_CENTER,
            intent="complaint",
        )
        (ev,) = engine.snapshot_events()
        assert ev.escalated is True
        assert ev.escalation_reason == EscalationReason.POLICY_FLAG
        assert ev.decision == PolicyDecision.FLAG

    def test_no_guard_result_yields_none_decision_and_confidence(
        self, engine: BridgeAnalytics
    ) -> None:
        engine.record_query(
            _bridge_result(with_guard=False),
            customer_id="cust_005",
            latency_ms=50.0,
            channel=Channel.WEB,
            intent="unknown",
        )
        (ev,) = engine.snapshot_events()
        assert ev.decision is None
        assert ev.confidence is None

    def test_negative_latency_clamped_to_zero(self, engine: BridgeAnalytics) -> None:
        engine.record_query(
            _bridge_result(),
            customer_id="cust_006",
            latency_ms=-5.0,
        )
        (ev,) = engine.snapshot_events()
        assert ev.latency_ms == 0.0

    def test_naive_timestamp_assumed_utc(self, engine: BridgeAnalytics) -> None:
        naive = datetime(2026, 1, 10, 12, 0)
        engine.record_query(
            _bridge_result(),
            customer_id="cust_007",
            latency_ms=10.0,
            timestamp=naive,
        )
        (ev,) = engine.snapshot_events()
        assert ev.timestamp.tzinfo is not None
        assert ev.timestamp.utcoffset() == timedelta(0)

    def test_none_channel_becomes_unknown(self, engine: BridgeAnalytics) -> None:
        engine.record_query(
            _bridge_result(),
            customer_id="cust_008",
            latency_ms=10.0,
            channel=None,
            intent=None,
        )
        (ev,) = engine.snapshot_events()
        assert ev.channel == "unknown"
        assert ev.intent == "unknown"

    def test_raw_string_channel_passes_through(self, engine: BridgeAnalytics) -> None:
        engine.record_query(
            _bridge_result(),
            customer_id="cust_009",
            latency_ms=10.0,
            channel="custom_channel",
            intent="other",
        )
        (ev,) = engine.snapshot_events()
        assert ev.channel == "custom_channel"
        assert ev.intent == "other"

    def test_empty_customer_id_does_not_crash(
        self, engine: BridgeAnalytics, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The engine must never bring down the hot path on bad telemetry —
        # banking traffic continues even if a logging key is malformed.
        with caplog.at_level(logging.WARNING):
            engine.record_query(
                _bridge_result(),
                customer_id="",
                latency_ms=10.0,
            )
        assert len(engine) == 0

    def test_pii_in_transcript_not_inspected_by_engine(self, engine: BridgeAnalytics) -> None:
        # LGPD Art. 12: engine must never inspect or store the prompt body.
        # We feed a CPF-like string and confirm only opaque keys land.
        engine.record_query(
            _bridge_result(prompt="meu CPF é 111.222.333-44, qual meu saldo?"),
            customer_id="hash:abc123",
            latency_ms=10.0,
            channel=Channel.WHATSAPP,
            intent="balance",
        )
        (ev,) = engine.snapshot_events()
        assert "111.222.333-44" not in ev.customer_id
        assert "111.222.333-44" not in ev.channel
        assert "111.222.333-44" not in ev.intent


# ---------------------------------------------------------------------------
# Capacity and eviction
# ---------------------------------------------------------------------------


class TestCapacityEviction:
    def test_oldest_event_evicted_when_capacity_exceeded(
        self, small_engine: BridgeAnalytics
    ) -> None:
        for i in range(5):
            small_engine.record_query(
                _bridge_result(),
                customer_id=f"cust_{i}",
                latency_ms=10.0,
                timestamp=_ts(2026, 1, 1, 0, i),
            )
        assert len(small_engine) == 3
        kept = {ev.customer_id for ev in small_engine.snapshot_events()}
        assert kept == {"cust_2", "cust_3", "cust_4"}


# ---------------------------------------------------------------------------
# retention_funnel
# ---------------------------------------------------------------------------


def _seed_funnel(engine: BridgeAnalytics) -> tuple[Period, Period]:
    """Seed the canonical funnel scenario used by several tests."""
    current = Period(start=_ts(2026, 1, 8), end=_ts(2026, 1, 15))
    prior = current.shift(-current.duration)

    # cust_A: prior + current (retained), one resolved + one escalated in current
    engine.record_query(
        _bridge_result(),
        customer_id="cust_A",
        latency_ms=100.0,
        timestamp=_ts(2026, 1, 3),
        intent="balance",
    )
    engine.record_query(
        _bridge_result(),
        customer_id="cust_A",
        latency_ms=110.0,
        timestamp=_ts(2026, 1, 10),
        intent="balance",
    )
    engine.record_query(
        _bridge_result(escalated=True, escalation_reason=EscalationReason.LOW_CONFIDENCE),
        customer_id="cust_A",
        latency_ms=200.0,
        timestamp=_ts(2026, 1, 13),
        intent="transfer",
    )
    # cust_B: prior only (churned)
    engine.record_query(
        _bridge_result(),
        customer_id="cust_B",
        latency_ms=120.0,
        timestamp=_ts(2026, 1, 4),
        intent="balance",
    )
    # cust_C: current only, new
    engine.record_query(
        _bridge_result(),
        customer_id="cust_C",
        latency_ms=90.0,
        timestamp=_ts(2026, 1, 11),
        intent="pix",
    )
    # cust_D: current only, new, escalated
    engine.record_query(
        _bridge_result(escalated=True, escalation_reason=EscalationReason.POLICY_ABSTAIN),
        customer_id="cust_D",
        latency_ms=150.0,
        timestamp=_ts(2026, 1, 12),
        intent="complaint",
    )
    return current, prior


class TestRetentionFunnel:
    def test_basic_cohort_arithmetic(self, engine: BridgeAnalytics) -> None:
        current, prior = _seed_funnel(engine)
        report = engine.retention_funnel(current)

        assert report.period == current
        assert report.prior_period == prior
        assert report.active_customers == 3  # A, C, D
        assert report.retained_customers == 1  # A
        assert report.churned_customers == 1  # B
        assert report.new_customers == 2  # C, D
        assert report.queries_total == 4  # A x2, C, D in current
        assert report.queries_resolved == 2  # A's 01-10 and C
        assert report.retention_rate == pytest.approx(0.5)  # 1/2
        assert report.resolution_rate == pytest.approx(0.5)  # 2/4

    def test_empty_prior_yields_zero_retention(self, engine: BridgeAnalytics) -> None:
        current = Period(start=_ts(2026, 2, 1), end=_ts(2026, 2, 8))
        engine.record_query(
            _bridge_result(),
            customer_id="cust_first",
            latency_ms=10.0,
            timestamp=_ts(2026, 2, 4),
            intent="balance",
        )
        report = engine.retention_funnel(current)
        assert report.retention_rate == 0.0
        assert report.active_customers == 1
        assert report.new_customers == 1

    def test_zero_queries_yields_zero_resolution(self, engine: BridgeAnalytics) -> None:
        current = Period(start=_ts(2026, 3, 1), end=_ts(2026, 3, 8))
        report = engine.retention_funnel(current)
        assert report.resolution_rate == 0.0
        assert report.queries_total == 0

    def test_bradesco_kpi_pass(self, engine: BridgeAnalytics) -> None:
        """A high-retention/high-resolution week clears both 0.90 and 0.83 floors."""
        current = Period(start=_ts(2026, 4, 8), end=_ts(2026, 4, 15))
        # 10 customers active in prior, 9 also active in current (= 0.90 retention)
        # All 9 queries resolved in current (= 1.0 resolution)
        for i in range(10):
            engine.record_query(
                _bridge_result(),
                customer_id=f"cust_{i:02d}",
                latency_ms=100.0,
                timestamp=_ts(2026, 4, 4, 0, i),
                intent="balance",
            )
        for i in range(9):
            engine.record_query(
                _bridge_result(),
                customer_id=f"cust_{i:02d}",
                latency_ms=100.0,
                timestamp=_ts(2026, 4, 10, 0, i),
                intent="balance",
            )
        report = engine.retention_funnel(current)
        assert report.retention_rate == pytest.approx(0.9)
        assert report.meets_retention_target() is True
        assert report.meets_resolution_target() is True

    def test_to_dict_round_trip(self, engine: BridgeAnalytics) -> None:
        current, _ = _seed_funnel(engine)
        d = engine.retention_funnel(current).to_dict()
        assert d["active_customers"] == 3
        assert d["new_customers"] == 2
        assert d["retained_customers"] == 1
        assert d["queries_total"] == 4


# ---------------------------------------------------------------------------
# intent_distribution
# ---------------------------------------------------------------------------


class TestIntentDistribution:
    def test_groups_by_intent(self, engine: BridgeAnalytics) -> None:
        period = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 31))
        for i, intent in enumerate(
            ["balance", "balance", "pix", "transfer", "balance", "pix"]
        ):
            engine.record_query(
                _bridge_result(),
                customer_id=f"c{i}",
                latency_ms=10.0,
                timestamp=_ts(2026, 1, 5, hour=i),
                intent=intent,
            )
        dist = engine.intent_distribution(period)
        assert dist == {"balance": 3, "pix": 2, "transfer": 1}

    def test_sorted_by_count_desc(self, engine: BridgeAnalytics) -> None:
        period = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 31))
        for i, intent in enumerate(["x", "y", "y", "z", "z", "z"]):
            engine.record_query(
                _bridge_result(),
                customer_id=f"c{i}",
                latency_ms=10.0,
                timestamp=_ts(2026, 1, 5, hour=i),
                intent=intent,
            )
        dist = engine.intent_distribution(period)
        assert list(dist.keys()) == ["z", "y", "x"]

    def test_outside_period_excluded(self, engine: BridgeAnalytics) -> None:
        period = Period(start=_ts(2026, 1, 8), end=_ts(2026, 1, 15))
        engine.record_query(
            _bridge_result(),
            customer_id="inside",
            latency_ms=10.0,
            timestamp=_ts(2026, 1, 10),
            intent="balance",
        )
        engine.record_query(
            _bridge_result(),
            customer_id="outside",
            latency_ms=10.0,
            timestamp=_ts(2026, 1, 1),
            intent="pix",
        )
        dist = engine.intent_distribution(period)
        assert dist == {"balance": 1}

    def test_empty_period_returns_empty_dict(self, engine: BridgeAnalytics) -> None:
        assert engine.intent_distribution(
            Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 2))
        ) == {}


# ---------------------------------------------------------------------------
# confidence_histogram
# ---------------------------------------------------------------------------


class TestConfidenceHistogram:
    def test_default_ten_bins(self, engine: BridgeAnalytics) -> None:
        period = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 31))
        for i, c in enumerate([0.05, 0.15, 0.95, 0.55, 0.75]):
            engine.record_query(
                _bridge_result(confidence=c),
                customer_id=f"c{i}",
                latency_ms=10.0,
                timestamp=_ts(2026, 1, 5, hour=i),
                intent="balance",
            )
        buckets = engine.confidence_histogram(period)
        assert len(buckets) == DEFAULT_HISTOGRAM_BINS
        assert buckets[0].count == 1  # 0.05
        assert buckets[1].count == 1  # 0.15
        assert buckets[5].count == 1  # 0.55
        assert buckets[7].count == 1  # 0.75
        assert buckets[9].count == 1  # 0.95
        total = sum(b.count for b in buckets)
        assert total == 5
        shares = sum(b.share for b in buckets)
        assert shares == pytest.approx(1.0)

    def test_perfect_confidence_lands_in_last_bucket(self, engine: BridgeAnalytics) -> None:
        period = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 31))
        engine.record_query(
            _bridge_result(confidence=1.0),
            customer_id="perfect",
            latency_ms=10.0,
            timestamp=_ts(2026, 1, 5),
            intent="balance",
        )
        buckets = engine.confidence_histogram(period, bins=10)
        assert buckets[-1].count == 1
        assert sum(b.count for b in buckets[:-1]) == 0

    def test_events_without_confidence_skipped(self, engine: BridgeAnalytics) -> None:
        period = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 31))
        engine.record_query(
            _bridge_result(with_guard=False),
            customer_id="no_guard",
            latency_ms=10.0,
            timestamp=_ts(2026, 1, 5),
            intent="balance",
        )
        engine.record_query(
            _bridge_result(confidence=0.5),
            customer_id="has_guard",
            latency_ms=10.0,
            timestamp=_ts(2026, 1, 6),
            intent="balance",
        )
        buckets = engine.confidence_histogram(period)
        assert sum(b.count for b in buckets) == 1

    def test_zero_bins_rejected(self, engine: BridgeAnalytics) -> None:
        period = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 31))
        with pytest.raises(ValueError, match="bins"):
            engine.confidence_histogram(period, bins=0)

    def test_negative_bins_rejected(self, engine: BridgeAnalytics) -> None:
        period = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 31))
        with pytest.raises(ValueError, match="bins"):
            engine.confidence_histogram(period, bins=-3)

    def test_bucket_edges_partition_unit_interval(self, engine: BridgeAnalytics) -> None:
        period = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 31))
        buckets = engine.confidence_histogram(period, bins=4)
        assert buckets[0].lower == 0.0
        assert buckets[-1].upper == pytest.approx(1.0)
        for left, right in zip(buckets[:-1], buckets[1:]):
            assert left.upper == pytest.approx(right.lower)

    def test_empty_histogram_has_zero_shares(self, engine: BridgeAnalytics) -> None:
        period = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 31))
        buckets = engine.confidence_histogram(period)
        assert all(b.share == 0.0 for b in buckets)
        assert all(b.count == 0 for b in buckets)


# ---------------------------------------------------------------------------
# peak_hours
# ---------------------------------------------------------------------------


class TestPeakHours:
    def test_sorted_by_volume_desc(self, engine: BridgeAnalytics) -> None:
        # 14:00 UTC: 3 events (Brazil afternoon peak)
        # 09:00 UTC: 1 event
        for minute in (0, 15, 30):
            engine.record_query(
                _bridge_result(),
                customer_id=f"c_pm_{minute}",
                latency_ms=100.0,
                timestamp=_ts(2026, 1, 10, 14, minute),
                intent="balance",
            )
        engine.record_query(
            _bridge_result(),
            customer_id="c_am",
            latency_ms=200.0,
            timestamp=_ts(2026, 1, 10, 9, 0),
            intent="balance",
        )
        stats = engine.peak_hours()
        assert [s.hour for s in stats] == [14, 9]
        assert stats[0].query_count == 3
        assert stats[1].query_count == 1
        assert stats[0].avg_latency_ms == pytest.approx(100.0)
        assert stats[1].avg_latency_ms == pytest.approx(200.0)

    def test_escalation_rate_per_hour(self, engine: BridgeAnalytics) -> None:
        for i in range(3):
            engine.record_query(
                _bridge_result(),
                customer_id=f"resolved_{i}",
                latency_ms=10.0,
                timestamp=_ts(2026, 1, 10, 16, i),
                intent="balance",
            )
        engine.record_query(
            _bridge_result(escalated=True, escalation_reason=EscalationReason.POLICY_ABSTAIN),
            customer_id="escalated",
            latency_ms=10.0,
            timestamp=_ts(2026, 1, 10, 16, 30),
            intent="complaint",
        )
        (stats,) = engine.peak_hours()
        assert stats.hour == 16
        assert stats.escalation_count == 1
        assert stats.query_count == 4
        assert stats.escalation_rate == pytest.approx(0.25)

    def test_empty_returns_empty_list(self, engine: BridgeAnalytics) -> None:
        assert engine.peak_hours() == []

    def test_filters_by_period(self, engine: BridgeAnalytics) -> None:
        engine.record_query(
            _bridge_result(),
            customer_id="inside",
            latency_ms=10.0,
            timestamp=_ts(2026, 1, 10, 14),
            intent="balance",
        )
        engine.record_query(
            _bridge_result(),
            customer_id="outside",
            latency_ms=10.0,
            timestamp=_ts(2026, 2, 1, 14),
            intent="balance",
        )
        period = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 31))
        stats = engine.peak_hours(period)
        assert len(stats) == 1
        assert stats[0].query_count == 1


# ---------------------------------------------------------------------------
# snapshot, reset, length
# ---------------------------------------------------------------------------


class TestSnapshotAndReset:
    def test_snapshot_events_full(self, engine: BridgeAnalytics) -> None:
        for i in range(3):
            engine.record_query(
                _bridge_result(),
                customer_id=f"c{i}",
                latency_ms=10.0,
                timestamp=_ts(2026, 1, 5, hour=i),
                intent="balance",
            )
        snap = engine.snapshot_events()
        assert isinstance(snap, tuple)
        assert len(snap) == 3

    def test_snapshot_period_filter(self, engine: BridgeAnalytics) -> None:
        engine.record_query(
            _bridge_result(),
            customer_id="inside",
            latency_ms=10.0,
            timestamp=_ts(2026, 1, 10),
            intent="balance",
        )
        engine.record_query(
            _bridge_result(),
            customer_id="outside",
            latency_ms=10.0,
            timestamp=_ts(2026, 2, 10),
            intent="balance",
        )
        period = Period(start=_ts(2026, 1, 1), end=_ts(2026, 1, 31))
        (ev,) = engine.snapshot_events(period)
        assert ev.customer_id == "inside"

    def test_snapshot_is_immutable_view(self, engine: BridgeAnalytics) -> None:
        engine.record_query(
            _bridge_result(),
            customer_id="c1",
            latency_ms=10.0,
            timestamp=_ts(2026, 1, 5),
            intent="balance",
        )
        snap = engine.snapshot_events()
        engine.record_query(
            _bridge_result(),
            customer_id="c2",
            latency_ms=10.0,
            timestamp=_ts(2026, 1, 6),
            intent="balance",
        )
        # The earlier snapshot must not see the later append.
        assert len(snap) == 1

    def test_reset_clears_ledger(self, engine: BridgeAnalytics) -> None:
        engine.record_query(
            _bridge_result(),
            customer_id="c",
            latency_ms=10.0,
            timestamp=_ts(2026, 1, 5),
            intent="balance",
        )
        assert len(engine) == 1
        engine.reset()
        assert len(engine) == 0

    def test_record_event_appends_directly(self, engine: BridgeAnalytics) -> None:
        engine.record_event(
            AnalyticsEvent(
                timestamp=_ts(2026, 1, 5),
                customer_id="replay",
                role=AgentRole.CHATBOT,
                channel="whatsapp",
                intent="balance",
                escalated=False,
                escalation_reason=None,
                decision=PolicyDecision.PASSTHROUGH,
                confidence=0.95,
                latency_ms=80.0,
            )
        )
        (ev,) = engine.snapshot_events()
        assert ev.customer_id == "replay"


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_record_query_does_not_lose_events(
        self, engine: BridgeAnalytics
    ) -> None:
        n_threads = 4
        per_thread = 50

        def worker(idx: int) -> None:
            for i in range(per_thread):
                engine.record_query(
                    _bridge_result(),
                    customer_id=f"t{idx}_c{i}",
                    latency_ms=10.0,
                    timestamp=_ts(2026, 1, 10, hour=(i % 24)),
                    intent="balance",
                )

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(engine) == n_threads * per_thread


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestChannelLabel:
    def test_none_returns_unknown(self) -> None:
        assert _channel_label(None) == "unknown"

    def test_channel_enum_returns_value(self) -> None:
        assert _channel_label(Channel.WHATSAPP) == "whatsapp"
        assert _channel_label(Channel.MOBILE_APP) == "mobile_app"

    def test_string_trimmed(self) -> None:
        assert _channel_label("  web  ") == "web"

    def test_empty_string_returns_unknown(self) -> None:
        assert _channel_label("   ") == "unknown"


class TestIntentLabel:
    def test_none_returns_unknown(self) -> None:
        assert _intent_label(None) == "unknown"

    def test_non_string_returns_unknown(self) -> None:
        assert _intent_label(123) == "unknown"  # type: ignore[arg-type]

    def test_string_trimmed(self) -> None:
        assert _intent_label("  balance  ") == "balance"

    def test_empty_string_returns_unknown(self) -> None:
        assert _intent_label("   ") == "unknown"


class TestEnsureIterable:
    def test_materializes_generator(self) -> None:
        def gen():
            yield AnalyticsEvent(
                timestamp=_ts(2026, 1, 5),
                customer_id="c",
                role=AgentRole.CHATBOT,
                channel="whatsapp",
                intent="balance",
                escalated=False,
                escalation_reason=None,
                decision=None,
                confidence=None,
                latency_ms=10.0,
            )

        out = _ensure_iterable(gen())
        assert isinstance(out, tuple)
        assert len(out) == 1


# ---------------------------------------------------------------------------
# Banking-context end-to-end
# ---------------------------------------------------------------------------


class TestBankingScenarios:
    def test_whatsapp_pix_voice_workflow(self, engine: BridgeAnalytics) -> None:
        """Smart Payments voice-PIX flow: low-confidence escalation captured."""
        engine.record_query(
            _bridge_result(
                role=AgentRole.SMART_PAYMENTS,
                prompt="pagar 150 reais pro Joao",
                decision=PolicyDecision.ABSTAIN,
                confidence=0.42,
                escalated=True,
                escalation_reason=EscalationReason.LOW_CONFIDENCE,
            ),
            customer_id="cust_voice",
            latency_ms=320.0,
            channel=Channel.WHATSAPP,
            intent="pix",
            timestamp=_ts(2026, 1, 10, 19),
        )
        (ev,) = engine.snapshot_events()
        assert ev.role == AgentRole.SMART_PAYMENTS
        assert ev.escalated is True
        assert ev.escalation_reason == EscalationReason.LOW_CONFIDENCE
        assert ev.confidence == pytest.approx(0.42)

    def test_call_center_assist_resolved(self, engine: BridgeAnalytics) -> None:
        engine.record_query(
            _bridge_result(role=AgentRole.CALL_CENTER, confidence=0.97),
            customer_id="cust_cc",
            latency_ms=80.0,
            channel=Channel.CALL_CENTER,
            intent="summary",
            timestamp=_ts(2026, 1, 10, 15),
        )
        period = Period(start=_ts(2026, 1, 8), end=_ts(2026, 1, 15))
        funnel = engine.retention_funnel(period)
        assert funnel.queries_resolved == 1
        assert funnel.queries_total == 1
        assert funnel.resolution_rate == 1.0
