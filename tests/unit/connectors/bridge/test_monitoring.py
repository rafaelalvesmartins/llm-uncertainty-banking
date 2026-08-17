# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for ``lub.connectors.bridge.monitoring``.

Exercises the Bridge platform health aggregator end-to-end:

* Every individual check (agents, backends, sla, confidence, escalation)
  in isolation, against a mocked platform / metrics / router.
* The aggregator (``health_check`` → ``alert_if_degraded`` →
  ``dashboard_data``) wiring, including the worst-state roll-up.
* Edge cases the banking deployment must survive without crashing:
  empty input, snapshot failure, individual check raising.

All collaborators (BridgePlatform, BridgeMetrics, BridgeRouter,
MetricsSnapshot, SLAViolation) are mocked. No LLM is invoked.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from lub.connectors.bridge import AgentRole
from lub.connectors.bridge.metrics import (
    MetricsSnapshot,
    SLAMetric,
    SLAViolation,
)
from lub.connectors.bridge.monitoring import (
    DEFAULT_CONFIDENCE_FLOOR,
    DEFAULT_ESCALATION_CEILING,
    Alert,
    AlertSeverity,
    BridgeMonitor,
    ComponentHealth,
    HealthState,
    HealthStatus,
)
from lub.connectors.bridge.router import Capability

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_snapshot(
    *,
    queries_total: int = 1000,
    escalations_total: int = 50,
    passthroughs_total: int = 950,
    guarded_total: int = 1000,
    retention_rate: float = 0.95,
    accuracy_rate: float = 0.95,
    resolution_rate: float = 0.95,
    escalation_rate: float = 0.05,
    avg_confidence: float = 0.85,
    avg_latency_ms: float = 800.0,
    call_time_reduction: float | None = 0.42,
) -> MetricsSnapshot:
    """Build a healthy ``MetricsSnapshot``; override per-test as needed."""
    return MetricsSnapshot(
        queries_total=queries_total,
        escalations_total=escalations_total,
        passthroughs_total=passthroughs_total,
        guarded_total=guarded_total,
        retention_rate=retention_rate,
        accuracy_rate=accuracy_rate,
        resolution_rate=resolution_rate,
        escalation_rate=escalation_rate,
        avg_confidence=avg_confidence,
        avg_latency_ms=avg_latency_ms,
        call_time_reduction=call_time_reduction,
        queries_by_channel={"whatsapp": 700, "mobile_app": 300},
        queries_by_intent={"balance_inquiry": 600, "transfer": 400},
        queries_by_role={"chatbot": 800, "smart_payments": 200},
        escalations_by_reason={"low_confidence": 50},
    )


def _healthy_backends() -> dict[str, dict[str, Any]]:
    """Two healthy backends covering TEXT_GENERATION + VISION."""
    return {
        "azure-gpt4o": {
            "enabled": True,
            "healthy": True,
            "consecutive_failures": 0,
            "total_calls": 1234,
            "total_failures": 1,
            "cooldown_remaining_seconds": 0.0,
            "ewma_latency_ms": 750.0,
            "cost_per_1k_tokens": 0.005,
            "capabilities": [
                Capability.TEXT_GENERATION.value,
                Capability.VISION.value,
            ],
        },
        "anthropic-sonnet": {
            "enabled": True,
            "healthy": True,
            "consecutive_failures": 0,
            "total_calls": 500,
            "total_failures": 0,
            "cooldown_remaining_seconds": 0.0,
            "ewma_latency_ms": 900.0,
            "cost_per_1k_tokens": 0.003,
            "capabilities": [Capability.TEXT_GENERATION.value],
        },
    }


@pytest.fixture
def platform() -> MagicMock:
    """Bridge platform mock with all three flagship roles registered."""
    p = MagicMock()
    p.roles = (
        AgentRole.CHATBOT,
        AgentRole.CALL_CENTER,
        AgentRole.SMART_PAYMENTS,
    )
    return p


@pytest.fixture
def metrics() -> MagicMock:
    """BridgeMetrics mock returning a healthy snapshot and no violations."""
    m = MagicMock()
    m.snapshot.return_value = _make_snapshot()
    m.check_sla.return_value = []
    return m


@pytest.fixture
def router() -> MagicMock:
    """BridgeRouter mock with two healthy backends."""
    r = MagicMock()
    r.health.return_value = _healthy_backends()
    return r


@pytest.fixture
def monitor(
    platform: MagicMock, metrics: MagicMock, router: MagicMock
) -> BridgeMonitor:
    return BridgeMonitor(platform, metrics, router)


# ---------------------------------------------------------------------------
# Construction / validation
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_construction_works(
        self, platform: MagicMock, metrics: MagicMock
    ) -> None:
        m = BridgeMonitor(platform, metrics)
        assert m is not None

    def test_router_is_optional(
        self, platform: MagicMock, metrics: MagicMock
    ) -> None:
        m = BridgeMonitor(platform, metrics, router=None)
        status = m.health_check()
        names = {c.name for c in status.components}
        assert "backends" not in names

    @pytest.mark.parametrize("bad", [-0.01, 1.01, -1.0, 2.0])
    def test_confidence_floor_out_of_range_raises(
        self, platform: MagicMock, metrics: MagicMock, bad: float
    ) -> None:
        with pytest.raises(ValueError, match="confidence_floor"):
            BridgeMonitor(platform, metrics, confidence_floor=bad)

    @pytest.mark.parametrize("bad", [-0.01, 1.01, -1.0, 2.0])
    def test_escalation_ceiling_out_of_range_raises(
        self, platform: MagicMock, metrics: MagicMock, bad: float
    ) -> None:
        with pytest.raises(ValueError, match="escalation_ceiling"):
            BridgeMonitor(platform, metrics, escalation_ceiling=bad)

    @pytest.mark.parametrize("ok", [0.0, 0.5, 1.0])
    def test_floor_and_ceiling_accept_inclusive_bounds(
        self, platform: MagicMock, metrics: MagicMock, ok: float
    ) -> None:
        BridgeMonitor(
            platform,
            metrics,
            confidence_floor=ok,
            escalation_ceiling=ok,
        )

    def test_defaults_track_published_constants(self) -> None:
        assert DEFAULT_CONFIDENCE_FLOOR == pytest.approx(0.60)
        assert DEFAULT_ESCALATION_CEILING == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# Value object serialization
# ---------------------------------------------------------------------------


class TestComponentHealth:
    def test_to_dict_round_trips_fields(self) -> None:
        c = ComponentHealth(
            name="agents",
            state=HealthState.HEALTHY,
            summary="ok",
            detail={"k": 1},
        )
        d = c.to_dict()
        assert d == {
            "name": "agents",
            "state": "healthy",
            "summary": "ok",
            "detail": {"k": 1},
        }

    def test_to_dict_copies_detail_top_level(self) -> None:
        # Shallow copy: adding new top-level keys to the returned dict
        # must not leak back into the frozen dataclass.
        c = ComponentHealth(
            name="x",
            state=HealthState.DEGRADED,
            summary="s",
            detail={"k": 1},
        )
        d = c.to_dict()
        d["detail"]["new_key"] = "leaked"
        assert "new_key" not in c.detail


class TestHealthStatus:
    def test_healthy_property_true_only_for_healthy(self) -> None:
        for state, expected in (
            (HealthState.HEALTHY, True),
            (HealthState.DEGRADED, False),
            (HealthState.UNHEALTHY, False),
        ):
            s = HealthStatus(state=state, components=())
            assert s.healthy is expected

    def test_to_dict_serializes_components_and_timestamp(self) -> None:
        c = ComponentHealth(
            name="x", state=HealthState.HEALTHY, summary="ok"
        )
        s = HealthStatus(state=HealthState.HEALTHY, components=(c,))
        d = s.to_dict()
        assert d["state"] == "healthy"
        assert d["healthy"] is True
        assert d["components"] == [c.to_dict()]
        assert "T" in d["timestamp"]


class TestAlert:
    def test_to_dict_coerces_numerics(self) -> None:
        a = Alert(
            severity=AlertSeverity.WARNING,
            component="sla",
            message="m",
            observed=0.8,
            target=0.9,
            detail={"k": "v"},
        )
        d = a.to_dict()
        assert d["severity"] == "warning"
        assert d["observed"] == 0.8
        assert d["target"] == 0.9
        assert d["detail"] == {"k": "v"}

    def test_to_dict_preserves_none_observed_target(self) -> None:
        a = Alert(
            severity=AlertSeverity.CRITICAL,
            component="agents",
            message="m",
        )
        d = a.to_dict()
        assert d["observed"] is None
        assert d["target"] is None


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHealthyPipeline:
    def test_full_pipeline_reports_healthy(self, monitor: BridgeMonitor) -> None:
        status = monitor.health_check()
        assert status.state is HealthState.HEALTHY
        assert status.healthy is True
        names = {c.name for c in status.components}
        assert names == {"agents", "backends", "sla", "confidence", "escalation"}
        for c in status.components:
            assert c.state is HealthState.HEALTHY

    def test_healthy_pipeline_emits_no_alerts(
        self, monitor: BridgeMonitor
    ) -> None:
        assert monitor.alert_if_degraded() == []


# ---------------------------------------------------------------------------
# Agents check
# ---------------------------------------------------------------------------


class TestAgentsCheck:
    def test_missing_required_role_is_unhealthy(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        platform.roles = (AgentRole.CHATBOT,)  # missing two roles
        m = BridgeMonitor(platform, metrics, router)
        status = m.health_check()
        agents = next(c for c in status.components if c.name == "agents")
        assert agents.state is HealthState.UNHEALTHY
        assert AgentRole.CALL_CENTER.value in agents.detail["missing"]
        assert AgentRole.SMART_PAYMENTS.value in agents.detail["missing"]
        assert status.state is HealthState.UNHEALTHY

    def test_narrowed_required_roles_pass_with_partial_deployment(
        self, platform: MagicMock, metrics: MagicMock
    ) -> None:
        platform.roles = (AgentRole.CHATBOT,)
        m = BridgeMonitor(
            platform,
            metrics,
            required_roles=[AgentRole.CHATBOT],
        )
        status = m.health_check()
        agents = next(c for c in status.components if c.name == "agents")
        assert agents.state is HealthState.HEALTHY

    def test_agents_check_handles_attribute_error_as_degraded(
        self, metrics: MagicMock, router: MagicMock
    ) -> None:
        broken_platform = MagicMock()
        type(broken_platform).roles = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        m = BridgeMonitor(broken_platform, metrics, router)
        status = m.health_check()
        agents = next(c for c in status.components if c.name == "agents")
        assert agents.state is HealthState.DEGRADED
        assert agents.detail["error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# Backends check
# ---------------------------------------------------------------------------


class TestBackendsCheck:
    def test_no_router_skips_backend_component(
        self, platform: MagicMock, metrics: MagicMock
    ) -> None:
        m = BridgeMonitor(platform, metrics, router=None)
        status = m.health_check()
        assert all(c.name != "backends" for c in status.components)

    def test_router_with_no_backends_unhealthy(
        self, platform: MagicMock, metrics: MagicMock
    ) -> None:
        empty_router = MagicMock()
        empty_router.health.return_value = {}
        m = BridgeMonitor(platform, metrics, empty_router)
        backends = next(
            c for c in m.health_check().components if c.name == "backends"
        )
        assert backends.state is HealthState.UNHEALTHY
        assert "no backends" in backends.summary

    def test_all_backends_unhealthy_is_unhealthy(
        self, platform: MagicMock, metrics: MagicMock
    ) -> None:
        r = MagicMock()
        health = _healthy_backends()
        for info in health.values():
            info["healthy"] = False
        r.health.return_value = health
        m = BridgeMonitor(platform, metrics, r)
        backends = next(
            c for c in m.health_check().components if c.name == "backends"
        )
        assert backends.state is HealthState.UNHEALTHY

    def test_some_backends_in_cooldown_is_degraded(
        self, platform: MagicMock, metrics: MagicMock
    ) -> None:
        r = MagicMock()
        health = _healthy_backends()
        health["anthropic-sonnet"]["healthy"] = False
        health["anthropic-sonnet"]["cooldown_remaining_seconds"] = 12.0
        r.health.return_value = health
        m = BridgeMonitor(platform, metrics, r)
        backends = next(
            c for c in m.health_check().components if c.name == "backends"
        )
        assert backends.state is HealthState.DEGRADED
        assert "anthropic-sonnet" in backends.detail["unhealthy"]

    def test_required_capability_missing_unhealthy(
        self, platform: MagicMock, metrics: MagicMock
    ) -> None:
        r = MagicMock()
        health = _healthy_backends()
        # Strip vision from the only backend that had it.
        health["azure-gpt4o"]["capabilities"] = [
            Capability.TEXT_GENERATION.value
        ]
        r.health.return_value = health
        m = BridgeMonitor(
            platform,
            metrics,
            r,
            required_capabilities=[Capability.VISION],
        )
        backends = next(
            c for c in m.health_check().components if c.name == "backends"
        )
        assert backends.state is HealthState.UNHEALTHY
        assert Capability.VISION.value in backends.detail["missing_capabilities"]

    def test_required_capability_only_on_unhealthy_backend_fails(
        self, platform: MagicMock, metrics: MagicMock
    ) -> None:
        r = MagicMock()
        health = _healthy_backends()
        # Vision-capable backend is in cooldown.
        health["azure-gpt4o"]["healthy"] = False
        r.health.return_value = health
        m = BridgeMonitor(
            platform,
            metrics,
            r,
            required_capabilities=[Capability.VISION],
        )
        backends = next(
            c for c in m.health_check().components if c.name == "backends"
        )
        assert backends.state is HealthState.UNHEALTHY

    def test_backend_check_raises_to_degraded(
        self, platform: MagicMock, metrics: MagicMock
    ) -> None:
        r = MagicMock()
        r.health.side_effect = RuntimeError("router crashed")
        m = BridgeMonitor(platform, metrics, r)
        backends = next(
            c for c in m.health_check().components if c.name == "backends"
        )
        assert backends.state is HealthState.DEGRADED
        assert backends.detail["error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# SLA check
# ---------------------------------------------------------------------------


class TestSlaCheck:
    def test_no_violations_is_healthy(self, monitor: BridgeMonitor) -> None:
        sla = next(
            c for c in monitor.health_check().components if c.name == "sla"
        )
        assert sla.state is HealthState.HEALTHY

    def test_latency_violation_promotes_to_unhealthy(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        metrics.check_sla.return_value = [
            SLAViolation(
                metric=SLAMetric.AVG_LATENCY_MS,
                observed=5000.0,
                target=3000.0,
                samples=1500,
            )
        ]
        m = BridgeMonitor(platform, metrics, router)
        sla = next(c for c in m.health_check().components if c.name == "sla")
        assert sla.state is HealthState.UNHEALTHY

    def test_zero_observed_promotes_to_unhealthy(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        # An observed value of 0.0 (e.g. accuracy_rate == 0) is treated as
        # catastrophic by the monitor.
        metrics.check_sla.return_value = [
            SLAViolation(
                metric=SLAMetric.ACCURACY_RATE,
                observed=0.0,
                target=0.95,
                samples=200,
            )
        ]
        m = BridgeMonitor(platform, metrics, router)
        sla = next(c for c in m.health_check().components if c.name == "sla")
        assert sla.state is HealthState.UNHEALTHY

    def test_non_latency_partial_violation_is_degraded(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        metrics.check_sla.return_value = [
            SLAViolation(
                metric=SLAMetric.RETENTION_RATE,
                observed=0.85,
                target=0.90,
                samples=2000,
            )
        ]
        m = BridgeMonitor(platform, metrics, router)
        sla = next(c for c in m.health_check().components if c.name == "sla")
        assert sla.state is HealthState.DEGRADED
        assert sla.detail["violations"][0]["metric"] == "retention_rate"

    def test_missing_snapshot_is_degraded(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        metrics.snapshot.side_effect = RuntimeError("metrics down")
        m = BridgeMonitor(platform, metrics, router)
        sla = next(c for c in m.health_check().components if c.name == "sla")
        assert sla.state is HealthState.DEGRADED
        assert "unavailable" in sla.summary

    def test_check_sla_raises_to_degraded(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        metrics.check_sla.side_effect = RuntimeError("sla crashed")
        m = BridgeMonitor(platform, metrics, router)
        sla = next(c for c in m.health_check().components if c.name == "sla")
        assert sla.state is HealthState.DEGRADED
        assert sla.detail["error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# Confidence check (low-confidence -> degraded analogue)
# ---------------------------------------------------------------------------


class TestConfidenceCheck:
    def test_high_confidence_healthy(self, monitor: BridgeMonitor) -> None:
        c = next(
            x for x in monitor.health_check().components if x.name == "confidence"
        )
        assert c.state is HealthState.HEALTHY
        assert c.detail["observed"] == pytest.approx(0.85)

    def test_low_confidence_degraded(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        metrics.snapshot.return_value = _make_snapshot(avg_confidence=0.40)
        m = BridgeMonitor(platform, metrics, router)
        c = next(x for x in m.health_check().components if x.name == "confidence")
        assert c.state is HealthState.DEGRADED
        assert "0.400" in c.summary
        assert c.detail["observed"] == pytest.approx(0.40)
        assert c.detail["floor"] == pytest.approx(DEFAULT_CONFIDENCE_FLOOR)

    def test_exactly_at_floor_is_healthy(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        metrics.snapshot.return_value = _make_snapshot(
            avg_confidence=DEFAULT_CONFIDENCE_FLOOR
        )
        m = BridgeMonitor(platform, metrics, router)
        c = next(x for x in m.health_check().components if x.name == "confidence")
        assert c.state is HealthState.HEALTHY

    def test_no_guarded_queries_is_healthy(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        metrics.snapshot.return_value = _make_snapshot(
            guarded_total=0,
            avg_confidence=0.0,
        )
        m = BridgeMonitor(platform, metrics, router)
        c = next(x for x in m.health_check().components if x.name == "confidence")
        assert c.state is HealthState.HEALTHY
        assert "no guarded queries" in c.summary

    def test_custom_floor_respected(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        # 0.80 floor — our default snapshot at 0.85 still passes.
        m = BridgeMonitor(platform, metrics, router, confidence_floor=0.80)
        c = next(x for x in m.health_check().components if x.name == "confidence")
        assert c.state is HealthState.HEALTHY
        # 0.90 floor — same snapshot now fails.
        m2 = BridgeMonitor(platform, metrics, router, confidence_floor=0.90)
        c2 = next(x for x in m2.health_check().components if x.name == "confidence")
        assert c2.state is HealthState.DEGRADED


# ---------------------------------------------------------------------------
# Escalation check (high -> degraded)
# ---------------------------------------------------------------------------


class TestEscalationCheck:
    def test_below_ceiling_healthy(self, monitor: BridgeMonitor) -> None:
        c = next(
            x for x in monitor.health_check().components if x.name == "escalation"
        )
        assert c.state is HealthState.HEALTHY

    def test_above_ceiling_degraded(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        metrics.snapshot.return_value = _make_snapshot(
            queries_total=1000,
            escalations_total=300,
            escalation_rate=0.30,
        )
        m = BridgeMonitor(platform, metrics, router)
        c = next(x for x in m.health_check().components if x.name == "escalation")
        assert c.state is HealthState.DEGRADED
        assert c.detail["observed"] == pytest.approx(0.30)
        assert c.detail["ceiling"] == pytest.approx(DEFAULT_ESCALATION_CEILING)

    def test_at_ceiling_is_healthy(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        # Comparison is strict > ceiling, so exact match must pass.
        metrics.snapshot.return_value = _make_snapshot(
            escalation_rate=DEFAULT_ESCALATION_CEILING,
        )
        m = BridgeMonitor(platform, metrics, router)
        c = next(x for x in m.health_check().components if x.name == "escalation")
        assert c.state is HealthState.HEALTHY

    def test_no_queries_is_healthy(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        metrics.snapshot.return_value = _make_snapshot(
            queries_total=0,
            escalations_total=0,
            escalation_rate=0.0,
        )
        m = BridgeMonitor(platform, metrics, router)
        c = next(x for x in m.health_check().components if x.name == "escalation")
        assert c.state is HealthState.HEALTHY
        assert "no queries" in c.summary


# ---------------------------------------------------------------------------
# alert_if_degraded
# ---------------------------------------------------------------------------


class TestAlertIfDegraded:
    def test_degraded_component_emits_warning(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        metrics.snapshot.return_value = _make_snapshot(avg_confidence=0.20)
        m = BridgeMonitor(platform, metrics, router)
        alerts = m.alert_if_degraded()
        confidence_alert = next(a for a in alerts if a.component == "confidence")
        assert confidence_alert.severity is AlertSeverity.WARNING
        assert confidence_alert.observed == pytest.approx(0.20)
        assert confidence_alert.target == pytest.approx(DEFAULT_CONFIDENCE_FLOOR)

    def test_unhealthy_component_emits_critical(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        platform.roles = ()  # nothing registered → UNHEALTHY
        m = BridgeMonitor(platform, metrics, router)
        alerts = m.alert_if_degraded()
        agents_alert = next(a for a in alerts if a.component == "agents")
        assert agents_alert.severity is AlertSeverity.CRITICAL

    def test_sla_violation_alert_carries_observed_and_target(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        metrics.check_sla.return_value = [
            SLAViolation(
                metric=SLAMetric.AVG_LATENCY_MS,
                observed=5000.0,
                target=3000.0,
                samples=1500,
            )
        ]
        m = BridgeMonitor(platform, metrics, router)
        alerts = m.alert_if_degraded()
        sla_alert = next(a for a in alerts if a.component == "sla")
        assert sla_alert.severity is AlertSeverity.CRITICAL
        assert sla_alert.observed == pytest.approx(5000.0)
        assert sla_alert.target == pytest.approx(3000.0)

    def test_all_healthy_yields_empty_alert_list(
        self, monitor: BridgeMonitor
    ) -> None:
        assert monitor.alert_if_degraded() == []


# ---------------------------------------------------------------------------
# Aggregator (worst-state roll-up + dashboard payload)
# ---------------------------------------------------------------------------


class TestAggregator:
    def test_worst_state_wins(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        # One DEGRADED (confidence) + one UNHEALTHY (agents) -> UNHEALTHY.
        platform.roles = ()
        metrics.snapshot.return_value = _make_snapshot(avg_confidence=0.10)
        m = BridgeMonitor(platform, metrics, router)
        assert m.health_check().state is HealthState.UNHEALTHY

    def test_degraded_alone_yields_degraded(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        metrics.snapshot.return_value = _make_snapshot(avg_confidence=0.10)
        m = BridgeMonitor(platform, metrics, router)
        assert m.health_check().state is HealthState.DEGRADED

    def test_dashboard_data_shape_is_stable(
        self, monitor: BridgeMonitor
    ) -> None:
        data = monitor.dashboard_data()
        assert set(data.keys()) == {
            "status",
            "metrics",
            "backends",
            "alerts",
            "config",
        }
        assert data["status"]["healthy"] is True
        assert data["alerts"] == []
        assert data["backends"] == _healthy_backends()
        # Config block surfaces the operator's tuning knobs.
        cfg = data["config"]
        assert cfg["confidence_floor"] == DEFAULT_CONFIDENCE_FLOOR
        assert cfg["escalation_ceiling"] == DEFAULT_ESCALATION_CEILING
        assert set(cfg["required_roles"]) == {r.value for r in AgentRole}

    def test_dashboard_data_when_snapshot_unavailable(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        metrics.snapshot.side_effect = RuntimeError("metrics down")
        m = BridgeMonitor(platform, metrics, router)
        data = m.dashboard_data()
        assert data["metrics"] is None
        assert data["backends"] == _healthy_backends()
        # The SLA check should have flagged DEGRADED because snapshot is gone.
        assert data["status"]["state"] in {"degraded", "unhealthy"}

    def test_dashboard_data_without_router(
        self, platform: MagicMock, metrics: MagicMock
    ) -> None:
        m = BridgeMonitor(platform, metrics, router=None)
        data = m.dashboard_data()
        assert data["backends"] is None
        assert all(
            c["name"] != "backends" for c in data["status"]["components"]
        )

    def test_dashboard_alerts_match_alert_if_degraded(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        # Drive two components into trouble at once.
        platform.roles = ()  # UNHEALTHY agents
        metrics.snapshot.return_value = _make_snapshot(
            queries_total=1000,
            escalations_total=300,
            escalation_rate=0.30,
        )
        m = BridgeMonitor(platform, metrics, router)
        data = m.dashboard_data()
        components_in_alerts = {a["component"] for a in data["alerts"]}
        assert {"agents", "escalation"}.issubset(components_in_alerts)

        # Same set of components from the direct API.
        direct = {a.component for a in m.alert_if_degraded()}
        assert {"agents", "escalation"}.issubset(direct)


# ---------------------------------------------------------------------------
# End-to-end pipeline scenarios (mirrors the 9-stage Bridge pipeline)
# ---------------------------------------------------------------------------


class TestEndToEndScenarios:
    def test_backend_timeout_surfaces_as_unhealthy_backends(
        self, platform: MagicMock, metrics: MagicMock
    ) -> None:
        # All backends are in cooldown after the upstream provider timeout-
        # storm — every entry reports healthy=False.
        r = MagicMock()
        health = _healthy_backends()
        for info in health.values():
            info["healthy"] = False
            info["cooldown_remaining_seconds"] = 30.0
            info["consecutive_failures"] = 5
        r.health.return_value = health
        m = BridgeMonitor(platform, metrics, r)
        status = m.health_check()
        assert status.state is HealthState.UNHEALTHY
        alerts = m.alert_if_degraded()
        assert any(
            a.component == "backends" and a.severity is AlertSeverity.CRITICAL
            for a in alerts
        )

    def test_low_confidence_path_triggers_escalation_alert(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        # Confidence collapsed AND escalation rate spiked — both should fire.
        metrics.snapshot.return_value = _make_snapshot(
            avg_confidence=0.30,
            queries_total=1000,
            escalations_total=250,
            escalation_rate=0.25,
        )
        m = BridgeMonitor(platform, metrics, router)
        alerts = m.alert_if_degraded()
        components = {a.component for a in alerts}
        assert "confidence" in components
        assert "escalation" in components
        # Both are DEGRADED individually -> overall DEGRADED, not UNHEALTHY.
        assert m.health_check().state is HealthState.DEGRADED

    def test_invalid_response_from_metrics_snapshot_does_not_crash(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        # Simulate the metrics layer returning a malformed object that
        # blows up when fields are read. The monitor must still produce
        # a structured status rather than raising.
        bad = MagicMock(spec=MetricsSnapshot)
        # Attribute access raises -> _check_confidence/_check_escalation
        # must wrap it.
        for attr in (
            "guarded_total",
            "queries_total",
            "avg_confidence",
            "escalation_rate",
            "escalations_total",
            "avg_latency_ms",
            "retention_rate",
            "accuracy_rate",
        ):
            setattr(
                type(bad),
                attr,
                property(
                    lambda self, _name=attr: (_ for _ in ()).throw(
                        AttributeError(_name)
                    )
                ),
            )
        metrics.snapshot.return_value = bad
        metrics.check_sla.return_value = []
        m = BridgeMonitor(platform, metrics, router)
        status = m.health_check()  # must not raise
        # All numeric checks should land in DEGRADED via the exception path.
        numeric = {
            c.name: c.state
            for c in status.components
            if c.name in {"sla", "confidence", "escalation"}
        }
        assert HealthState.DEGRADED in numeric.values()

    def test_empty_input_no_traffic_yet_is_healthy(
        self, platform: MagicMock, metrics: MagicMock, router: MagicMock
    ) -> None:
        # Cold-start: zero queries, zero guarded, zero escalations.
        metrics.snapshot.return_value = _make_snapshot(
            queries_total=0,
            escalations_total=0,
            passthroughs_total=0,
            guarded_total=0,
            retention_rate=0.0,
            accuracy_rate=0.0,
            resolution_rate=0.0,
            escalation_rate=0.0,
            avg_confidence=0.0,
            avg_latency_ms=0.0,
            call_time_reduction=None,
        )
        m = BridgeMonitor(platform, metrics, router)
        status = m.health_check()
        # Numeric checks should *not* flag during cold start.
        for c in status.components:
            if c.name in {"confidence", "escalation"}:
                assert c.state is HealthState.HEALTHY
        # Overall should remain healthy assuming agents + backends are OK.
        assert status.state is HealthState.HEALTHY
