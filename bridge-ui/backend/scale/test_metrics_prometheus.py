# Copyright 2026 Rafael Martins Alves — Apache-2.0
"""Tests for scale/metrics_prometheus.py.

Guard: ``pytest.importorskip`` skips the whole module if ``prometheus_client``
is not installed (i.e. requirements-scale.txt was not applied), so the base
test suite remains green on a plain ``pip install -r requirements.txt``.
"""

from __future__ import annotations

import pytest

prometheus_client = pytest.importorskip("prometheus_client")

# Import under test only after the guard above passes. Flat-layout import with a
# package-mode fallback, matching the rest of the suite (backend/ has no __init__.py).
try:
    from scale.metrics_prometheus import (  # noqa: E402
        REGISTRY,
        metrics_text,
        record_query,
    )
except ImportError:  # package-mode (backend.scale.*)
    from backend.scale.metrics_prometheus import (  # type: ignore[no-redef]  # noqa: E402
        REGISTRY,
        metrics_text,
        record_query,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scrape() -> str:
    """Return the full scrape text as a UTF-8 string."""
    body, _ct = metrics_text()
    return body.decode("utf-8")


def _counter_value(decision: str, intent: str, channel: str) -> float:
    """Read the current value of bridge_queries_total for a label set."""
    # prometheus_client names the Counter's metric FAMILY "bridge_queries"
    # (it strips the "_total" suffix) while the value SAMPLE is named
    # "bridge_queries_total". Match the sample by name so we pick the counter
    # value (not the "_created" timestamp sample) regardless of family naming.
    for mf in REGISTRY.collect():
        for sample in mf.samples:
            if (
                sample.name == "bridge_queries_total"
                and sample.labels.get("decision") == decision
                and sample.labels.get("intent") == intent
                and sample.labels.get("channel") == channel
            ):
                return sample.value
    return 0.0


def _gauge_value(metric_name: str) -> float:
    """Read the current value of a gauge by name."""
    for mf in REGISTRY.collect():
        if mf.name == metric_name:
            for sample in mf.samples:
                return sample.value
    return 0.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRecordQueryCounter:
    """record_query() increments bridge_queries_total with the right labels."""

    def test_counter_increments_once(self) -> None:
        before = _counter_value("PASSTHROUGH", "balance_inquiry", "api")
        record_query(
            latency_ms=42.0,
            decision="PASSTHROUGH",
            intent="balance_inquiry",
            channel="api",
        )
        after = _counter_value("PASSTHROUGH", "balance_inquiry", "api")
        assert after == before + 1.0

    def test_counter_increments_multiple(self) -> None:
        before = _counter_value("FLAG", "fraud_check", "chatbot")
        record_query(latency_ms=88.0, decision="FLAG", intent="fraud_check", channel="chatbot")
        record_query(latency_ms=91.0, decision="FLAG", intent="fraud_check", channel="chatbot")
        after = _counter_value("FLAG", "fraud_check", "chatbot")
        assert after == before + 2.0

    def test_distinct_decisions_are_independent(self) -> None:
        before_reask = _counter_value("REASK", "credit_limit", "api")
        before_escalate = _counter_value("ESCALATE", "credit_limit", "api")
        record_query(latency_ms=55.0, decision="REASK", intent="credit_limit", channel="api")
        after_reask = _counter_value("REASK", "credit_limit", "api")
        after_escalate = _counter_value("ESCALATE", "credit_limit", "api")
        assert after_reask == before_reask + 1.0
        assert after_escalate == before_escalate  # untouched

    def test_default_channel_is_api(self) -> None:
        before = _counter_value("PASSTHROUGH", "faq", "api")
        record_query(latency_ms=10.0, decision="PASSTHROUGH", intent="faq")  # no channel
        after = _counter_value("PASSTHROUGH", "faq", "api")
        assert after == before + 1.0


class TestRecordQueryHistogram:
    """record_query() observes the histogram in seconds."""

    def test_histogram_sample_count_grows(self) -> None:
        def _count() -> float:
            for mf in REGISTRY.collect():
                if mf.name == "bridge_query_latency_seconds":
                    for s in mf.samples:
                        if (
                            s.name == "bridge_query_latency_seconds_count"
                            and s.labels.get("decision") == "PASSTHROUGH"
                            and s.labels.get("intent") == "hist_test"
                        ):
                            return s.value
            return 0.0

        before = _count()
        record_query(latency_ms=120.0, decision="PASSTHROUGH", intent="hist_test")
        after = _count()
        assert after == before + 1.0

    def test_histogram_sum_reflects_latency(self) -> None:
        def _sum() -> float:
            for mf in REGISTRY.collect():
                if mf.name == "bridge_query_latency_seconds":
                    for s in mf.samples:
                        if (
                            s.name == "bridge_query_latency_seconds_sum"
                            and s.labels.get("decision") == "FLAG"
                            and s.labels.get("intent") == "sum_test"
                        ):
                            return s.value
            return 0.0

        before = _sum()
        record_query(latency_ms=500.0, decision="FLAG", intent="sum_test")
        after = _sum()
        # 500 ms → 0.5 s added to sum
        assert abs((after - before) - 0.5) < 1e-9


class TestRateGauges:
    """Resolution and escalation rate gauges are updated after record_query."""

    def test_resolution_rate_after_passthrough(self) -> None:
        # After at least one PASSTHROUGH the gauge must be in (0, 1].
        record_query(latency_ms=30.0, decision="PASSTHROUGH", intent="rate_test", channel="api")
        rate = _gauge_value("bridge_resolution_rate_approx")
        assert 0.0 < rate <= 1.0

    def test_escalation_rate_after_escalate(self) -> None:
        record_query(latency_ms=300.0, decision="ESCALATE", intent="rate_test", channel="api")
        rate = _gauge_value("bridge_escalation_rate_approx")
        assert 0.0 < rate <= 1.0

    def test_rates_are_fractions(self) -> None:
        resolution = _gauge_value("bridge_resolution_rate_approx")
        escalation = _gauge_value("bridge_escalation_rate_approx")
        assert 0.0 <= resolution <= 1.0
        assert 0.0 <= escalation <= 1.0


class TestMetricsText:
    """metrics_text() produces valid Prometheus exposition output."""

    def test_returns_bytes_and_content_type(self) -> None:
        body, ct = metrics_text()
        assert isinstance(body, bytes)
        assert "text/plain" in ct

    def test_contains_latency_histogram_name(self) -> None:
        text = _scrape()
        assert "bridge_query_latency_seconds" in text

    def test_contains_queries_counter_name(self) -> None:
        text = _scrape()
        assert "bridge_queries_total" in text

    def test_contains_resolution_rate_gauge_name(self) -> None:
        text = _scrape()
        assert "bridge_resolution_rate_approx" in text

    def test_contains_escalation_rate_gauge_name(self) -> None:
        text = _scrape()
        assert "bridge_escalation_rate_approx" in text

    def test_decision_labels_appear_in_output(self) -> None:
        # Drive each decision label through so it shows up in the exposition.
        for decision in ("PASSTHROUGH", "FLAG", "REASK", "ESCALATE"):
            record_query(
                latency_ms=50.0,
                decision=decision,
                intent="label_coverage",
                channel="api",
            )
        text = _scrape()
        for decision in ("PASSTHROUGH", "FLAG", "REASK", "ESCALATE"):
            assert decision in text

    def test_intent_label_appears_in_output(self) -> None:
        record_query(
            latency_ms=75.0,
            decision="PASSTHROUGH",
            intent="unique_intent_xyz",
            channel="api",
        )
        text = _scrape()
        assert "unique_intent_xyz" in text

    def test_channel_label_appears_in_output(self) -> None:
        record_query(
            latency_ms=20.0,
            decision="PASSTHROUGH",
            intent="chan_test",
            channel="call_center",
        )
        text = _scrape()
        assert "call_center" in text
