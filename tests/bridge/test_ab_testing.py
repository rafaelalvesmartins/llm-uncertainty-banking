# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :mod:`lub.connectors.bridge.ab_testing`.

Bridge is the central hub of the Bradesco banking AI platform; the A/B
testing framework is what lets operators swap LLM providers (Azure
OpenAI vs. Anthropic vs. self-hosted) under controlled experimentation.
Because every promotion decision is reviewable under SR 11-7 and BCB
4893, the framework's contract is unusually strict: deterministic
bucketing, no silent fallbacks, immutable specs, and refusal to call a
winner without enough samples. These tests pin all four properties.

The framework does not call any LLM itself — it returns a model
identifier for the caller to route through :class:`BridgeRouter`. So
the "mocked LLM calls" required by the task surface here as
:class:`GuardResult`-shaped verdicts fed into :meth:`record_outcome`;
no network or model is ever touched.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from lub.connectors.bridge.ab_testing import (
    _MIN_SAMPLES_FOR_VERDICT,
    ABTestingFramework,
    Experiment,
    ExperimentResult,
    ExperimentStatus,
    OptimisationMetric,
    UnknownExperimentError,
    UnknownVariantError,
    VariantAssignment,
    VariantMetrics,
    _decision_passthrough,
    _pick_winner,
    _standard_normal_cdf,
    _two_proportion_z_test,
    _welch_t_test_from_means,
)
from lub.guard import PolicyDecision

# ---------------------------------------------------------------------------
# Mock verdict builders
# ---------------------------------------------------------------------------
#
# The real :class:`~lub.guard.GuardResult` stores its decision under
# ``outcome.decision``; the framework's ``_decision_passthrough`` helper
# duck-types on ``policy_outcome.decision`` or a top-level ``decision``.
# Tests therefore build :class:`SimpleNamespace` stand-ins that satisfy
# the framework's contract without dragging in the full guard object —
# this mirrors what real banking integrations do when surfacing a
# verdict to the experimentation layer.


def _passthrough_verdict() -> SimpleNamespace:
    """Verdict shaped like a PASSTHROUGH guard outcome."""
    return SimpleNamespace(
        policy_outcome=SimpleNamespace(decision=PolicyDecision.PASSTHROUGH),
    )


def _abstain_verdict() -> SimpleNamespace:
    """Verdict shaped like an ABSTAIN guard outcome (counts as non-accurate)."""
    return SimpleNamespace(
        policy_outcome=SimpleNamespace(decision=PolicyDecision.ABSTAIN),
    )


def _flag_verdict() -> SimpleNamespace:
    return SimpleNamespace(
        policy_outcome=SimpleNamespace(decision=PolicyDecision.FLAG),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def framework() -> ABTestingFramework:
    """Fresh framework per test — no shared experiment state."""
    return ABTestingFramework()


@pytest.fixture
def basic_experiment() -> Experiment:
    """50/50 split between Azure OpenAI (control) and Anthropic (treatment)."""
    return Experiment(
        name="azure-vs-anthropic-2026q2",
        control_model="azure-openai-gpt-4o",
        treatment_model="anthropic-claude-opus-4-7",
        traffic_split=0.5,
        optimise=OptimisationMetric.ACCURACY,
        description="Provider bake-off against Bradesco's 95% accuracy SLA",
    )


@pytest.fixture
def registered_framework(
    framework: ABTestingFramework, basic_experiment: Experiment
) -> ABTestingFramework:
    """Framework with one running experiment registered."""
    framework.create_experiment(basic_experiment)
    return framework


# ---------------------------------------------------------------------------
# Experiment (Pydantic spec)
# ---------------------------------------------------------------------------


class TestExperimentSpec:
    """Pydantic validation on the immutable experiment declaration."""

    def test_valid_experiment_constructs(self, basic_experiment: Experiment) -> None:
        assert basic_experiment.control_model == "azure-openai-gpt-4o"
        assert basic_experiment.treatment_model == "anthropic-claude-opus-4-7"
        assert basic_experiment.traffic_split == pytest.approx(0.5)
        assert basic_experiment.optimise is OptimisationMetric.ACCURACY

    def test_experiment_is_frozen(self, basic_experiment: Experiment) -> None:
        """Mutating an experiment must fail — the audit trail relies on identity."""
        with pytest.raises((TypeError, ValueError)):
            basic_experiment.traffic_split = 0.7  # type: ignore[misc]

    def test_treatment_must_differ_from_control(self) -> None:
        with pytest.raises(ValueError, match="must differ from control_model"):
            Experiment(
                name="exp",
                control_model="azure-openai-gpt-4o",
                treatment_model="azure-openai-gpt-4o",
                traffic_split=0.5,
            )

    @pytest.mark.parametrize("split", [-0.01, 1.01, 2.0, -10.0])
    def test_traffic_split_must_be_between_0_and_1(self, split: float) -> None:
        with pytest.raises(ValueError):
            Experiment(
                name="exp",
                control_model="a",
                treatment_model="b",
                traffic_split=split,
            )

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            Experiment(name="", control_model="a", treatment_model="b", traffic_split=0.5)

    def test_extra_fields_rejected(self) -> None:
        """``extra='forbid'`` keeps stray fields from polluting the audit log."""
        with pytest.raises(ValueError):
            Experiment(
                name="exp",
                control_model="a",
                treatment_model="b",
                traffic_split=0.5,
                stray_field="oops",  # type: ignore[call-arg]
            )

    def test_default_metric_is_accuracy(self) -> None:
        """Banking governance prefers accuracy over latency by default."""
        exp = Experiment(name="x", control_model="a", treatment_model="b", traffic_split=0.5)
        assert exp.optimise is OptimisationMetric.ACCURACY


# ---------------------------------------------------------------------------
# Registration / lifecycle
# ---------------------------------------------------------------------------


class TestFrameworkRegistration:
    def test_create_experiment_makes_it_listable(
        self, framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        framework.create_experiment(basic_experiment)
        assert basic_experiment.name in framework.list_experiments()
        assert framework.get_status(basic_experiment.name) is ExperimentStatus.RUNNING

    def test_duplicate_name_refused(
        self, framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        """Silent overwrite would discard accumulated counters — banking refuses."""
        framework.create_experiment(basic_experiment)
        with pytest.raises(ValueError, match="already registered"):
            framework.create_experiment(basic_experiment)

    def test_get_experiment_returns_immutable_spec(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        retrieved = registered_framework.get_experiment(basic_experiment.name)
        assert retrieved == basic_experiment

    def test_get_unknown_experiment_raises(self, framework: ABTestingFramework) -> None:
        with pytest.raises(UnknownExperimentError, match="not registered"):
            framework.get_experiment("ghost")

    def test_set_status_to_completed_and_back(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        registered_framework.set_status(basic_experiment.name, ExperimentStatus.PAUSED)
        assert registered_framework.get_status(basic_experiment.name) is ExperimentStatus.PAUSED
        registered_framework.set_status(basic_experiment.name, ExperimentStatus.COMPLETED)
        assert registered_framework.get_status(basic_experiment.name) is ExperimentStatus.COMPLETED

    def test_set_status_on_unknown_experiment_raises(
        self, framework: ABTestingFramework
    ) -> None:
        with pytest.raises(UnknownExperimentError):
            framework.set_status("ghost", ExperimentStatus.PAUSED)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


class TestRouting:
    def test_unknown_experiment_raises(self, framework: ABTestingFramework) -> None:
        with pytest.raises(UnknownExperimentError):
            framework.route_traffic("ghost", "session-001")

    def test_assignment_is_deterministic(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        """Same (experiment, session) must always land on the same variant."""
        first = registered_framework.route_traffic(basic_experiment.name, "customer-42")
        for _ in range(50):
            again = registered_framework.route_traffic(basic_experiment.name, "customer-42")
            assert again.variant == first.variant
            assert again.model_id == first.model_id
            assert again.bucket == first.bucket

    def test_bucket_within_resolution_range(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        for i in range(20):
            assignment = registered_framework.route_traffic(
                basic_experiment.name, f"customer-{i}"
            )
            assert 0 <= assignment.bucket < 10_000

    def test_full_treatment_routes_all_to_treatment(
        self, framework: ABTestingFramework
    ) -> None:
        exp = Experiment(
            name="all-treatment",
            control_model="a",
            treatment_model="b",
            traffic_split=1.0,
        )
        framework.create_experiment(exp)
        for i in range(50):
            assignment = framework.route_traffic(exp.name, f"s-{i}")
            assert assignment.variant == "treatment"
            assert assignment.model_id == "b"

    def test_zero_treatment_routes_all_to_control(
        self, framework: ABTestingFramework
    ) -> None:
        exp = Experiment(
            name="no-treatment",
            control_model="a",
            treatment_model="b",
            traffic_split=0.0,
        )
        framework.create_experiment(exp)
        for i in range(50):
            assignment = framework.route_traffic(exp.name, f"s-{i}")
            assert assignment.variant == "control"
            assert assignment.model_id == "a"

    def test_split_approximately_matches_target(
        self, framework: ABTestingFramework
    ) -> None:
        """Over many sessions, the empirical split should hug the target."""
        exp = Experiment(
            name="split-check",
            control_model="a",
            treatment_model="b",
            traffic_split=0.25,
        )
        framework.create_experiment(exp)
        n = 2000
        treatment_count = sum(
            framework.route_traffic(exp.name, f"session-{i}").variant == "treatment"
            for i in range(n)
        )
        observed = treatment_count / n
        # SHA-256 hashing gives a near-uniform distribution; allow ±3%.
        assert abs(observed - 0.25) < 0.03

    def test_paused_experiment_falls_back_to_control(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        """Pause = revert to incumbent (BCB 4893's conservative bias)."""
        registered_framework.set_status(basic_experiment.name, ExperimentStatus.PAUSED)
        for i in range(20):
            assignment = registered_framework.route_traffic(
                basic_experiment.name, f"s-{i}"
            )
            assert assignment.variant == "control"
            assert assignment.model_id == basic_experiment.control_model

    def test_completed_experiment_falls_back_to_control(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        registered_framework.set_status(basic_experiment.name, ExperimentStatus.COMPLETED)
        assignment = registered_framework.route_traffic(basic_experiment.name, "s-1")
        assert assignment.variant == "control"

    def test_empty_session_id_still_routes(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        """Edge case: empty string is still a valid hash input."""
        assignment = registered_framework.route_traffic(basic_experiment.name, "")
        assert assignment.variant in {"control", "treatment"}
        assert 0 <= assignment.bucket < 10_000

    def test_assignment_metadata_complete(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        assignment = registered_framework.route_traffic(
            basic_experiment.name, "s-1", query="Qual meu saldo?"
        )
        assert isinstance(assignment, VariantAssignment)
        assert assignment.experiment == basic_experiment.name
        assert assignment.session_id == "s-1"
        assert assignment.timestamp is not None

    def test_query_does_not_affect_bucket(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        """Customer query content must never change the assignment."""
        a = registered_framework.route_traffic(
            basic_experiment.name, "s-1", query="Qual meu saldo?"
        )
        b = registered_framework.route_traffic(
            basic_experiment.name, "s-1", query="Como pago meu boleto?"
        )
        c = registered_framework.route_traffic(basic_experiment.name, "s-1", query=None)
        assert a.bucket == b.bucket == c.bucket
        assert a.variant == b.variant == c.variant


# ---------------------------------------------------------------------------
# Outcome recording
# ---------------------------------------------------------------------------


class TestRecordOutcome:
    def test_record_increments_samples_and_passthrough(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        registered_framework.record_outcome(
            basic_experiment.name,
            "control",
            guard_result=_passthrough_verdict(),
            escalated=False,
            latency_ms=120.0,
            confidence=0.91,
        )
        snap = registered_framework.snapshot(basic_experiment.name)
        assert snap["control"]["samples"] == 1.0
        assert snap["control"]["accuracy"] == 1.0
        assert snap["control"]["retention"] == 1.0
        assert snap["control"]["avg_latency_ms"] == pytest.approx(120.0)
        assert snap["control"]["avg_confidence"] == pytest.approx(0.91)

    def test_abstain_does_not_count_as_accurate(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        registered_framework.record_outcome(
            basic_experiment.name,
            "treatment",
            guard_result=_abstain_verdict(),
            escalated=True,
            latency_ms=200.0,
        )
        snap = registered_framework.snapshot(basic_experiment.name)
        assert snap["treatment"]["accuracy"] == 0.0
        assert snap["treatment"]["retention"] == 0.0

    def test_flag_does_not_count_as_accurate(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        registered_framework.record_outcome(
            basic_experiment.name,
            "control",
            guard_result=_flag_verdict(),
            escalated=False,
            latency_ms=100.0,
        )
        snap = registered_framework.snapshot(basic_experiment.name)
        assert snap["control"]["accuracy"] == 0.0
        assert snap["control"]["retention"] == 1.0  # not escalated

    def test_missing_guard_counts_as_non_accurate(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        registered_framework.record_outcome(
            basic_experiment.name,
            "control",
            guard_result=None,
            escalated=False,
            latency_ms=50.0,
        )
        snap = registered_framework.snapshot(basic_experiment.name)
        assert snap["control"]["accuracy"] == 0.0

    def test_unknown_experiment_raises(self, framework: ABTestingFramework) -> None:
        with pytest.raises(UnknownExperimentError):
            framework.record_outcome(
                "ghost", "control", escalated=False, latency_ms=10.0
            )

    def test_unknown_variant_raises(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        """Typo in variant must fail loudly — silent best-guess would corrupt the test."""
        with pytest.raises(UnknownVariantError, match="control.*treatment"):
            registered_framework.record_outcome(
                basic_experiment.name,
                "challenger",  # typo
                escalated=False,
                latency_ms=10.0,
            )

    def test_negative_latency_rejected(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        with pytest.raises(ValueError, match="latency_ms must be >= 0"):
            registered_framework.record_outcome(
                basic_experiment.name,
                "control",
                escalated=False,
                latency_ms=-1.0,
            )

    def test_completed_experiment_rejects_outcomes(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        """Sign-off is final: late callbacks must not retroactively change a result."""
        registered_framework.set_status(basic_experiment.name, ExperimentStatus.COMPLETED)
        with pytest.raises(RuntimeError, match="COMPLETED"):
            registered_framework.record_outcome(
                basic_experiment.name,
                "control",
                escalated=False,
                latency_ms=10.0,
            )

    def test_paused_experiment_still_accepts_outcomes(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        """Paused = no new buckets, but the in-flight calls still get recorded."""
        registered_framework.set_status(basic_experiment.name, ExperimentStatus.PAUSED)
        registered_framework.record_outcome(
            basic_experiment.name,
            "control",
            guard_result=_passthrough_verdict(),
            escalated=False,
            latency_ms=50.0,
        )
        snap = registered_framework.snapshot(basic_experiment.name)
        assert snap["control"]["samples"] == 1.0

    def test_running_means_update_correctly(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        for latency, conf in [(100.0, 0.8), (200.0, 0.9), (300.0, 1.0)]:
            registered_framework.record_outcome(
                basic_experiment.name,
                "control",
                guard_result=_passthrough_verdict(),
                escalated=False,
                latency_ms=latency,
                confidence=conf,
            )
        snap = registered_framework.snapshot(basic_experiment.name)
        assert snap["control"]["samples"] == 3.0
        assert snap["control"]["avg_latency_ms"] == pytest.approx(200.0)
        assert snap["control"]["avg_confidence"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def _seed_arm(
    framework: ABTestingFramework,
    name: str,
    variant: str,
    *,
    n: int,
    successes: int,
    latency_ms: float = 100.0,
) -> None:
    """Helper: pump *n* outcomes into *variant* with *successes* PASSTHROUGH."""
    for i in range(n):
        framework.record_outcome(
            name,
            variant,
            guard_result=_passthrough_verdict() if i < successes else _abstain_verdict(),
            escalated=(i >= successes),
            latency_ms=latency_ms,
        )


class TestAnalyse:
    def test_inconclusive_below_minimum_samples(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        _seed_arm(
            registered_framework,
            basic_experiment.name,
            "control",
            n=_MIN_SAMPLES_FOR_VERDICT - 1,
            successes=_MIN_SAMPLES_FOR_VERDICT - 1,
        )
        _seed_arm(
            registered_framework,
            basic_experiment.name,
            "treatment",
            n=_MIN_SAMPLES_FOR_VERDICT - 1,
            successes=0,
        )
        result = registered_framework.analyse(basic_experiment.name)
        assert result.winner == "inconclusive"
        assert "inconclusive" in result.rationale
        assert result.p_value == 1.0

    def test_treatment_wins_clearly(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        """A large, lopsided sample should declare the treatment as winner."""
        n = 500
        _seed_arm(
            registered_framework, basic_experiment.name, "control", n=n, successes=300
        )
        _seed_arm(
            registered_framework, basic_experiment.name, "treatment", n=n, successes=480
        )
        result = registered_framework.analyse(basic_experiment.name)
        assert result.winner == "treatment"
        assert result.p_value < 0.05
        assert result.effect_size > 0
        assert result.samples_control == n
        assert result.samples_treatment == n

    def test_control_wins_clearly(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        n = 500
        _seed_arm(
            registered_framework, basic_experiment.name, "control", n=n, successes=480
        )
        _seed_arm(
            registered_framework, basic_experiment.name, "treatment", n=n, successes=300
        )
        result = registered_framework.analyse(basic_experiment.name)
        assert result.winner == "control"
        assert result.p_value < 0.05
        assert result.effect_size < 0

    def test_no_significant_difference_is_inconclusive(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        n = 200
        _seed_arm(
            registered_framework, basic_experiment.name, "control", n=n, successes=150
        )
        _seed_arm(
            registered_framework,
            basic_experiment.name,
            "treatment",
            n=n,
            successes=152,  # near-identical share
        )
        result = registered_framework.analyse(basic_experiment.name)
        assert result.winner == "inconclusive"
        assert result.p_value > 0.05

    def test_analyse_unknown_raises(self, framework: ABTestingFramework) -> None:
        with pytest.raises(UnknownExperimentError):
            framework.analyse("ghost")

    def test_analyse_does_not_mutate_counters(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        """Interim peeks must not change the state — analysis is idempotent."""
        _seed_arm(
            registered_framework, basic_experiment.name, "control", n=40, successes=35
        )
        _seed_arm(
            registered_framework, basic_experiment.name, "treatment", n=40, successes=38
        )
        snap_before = registered_framework.snapshot(basic_experiment.name)
        registered_framework.analyse(basic_experiment.name)
        registered_framework.analyse(basic_experiment.name)
        snap_after = registered_framework.snapshot(basic_experiment.name)
        assert snap_before == snap_after

    def test_retention_metric(self, framework: ABTestingFramework) -> None:
        exp = Experiment(
            name="retention-exp",
            control_model="azure",
            treatment_model="anthropic",
            traffic_split=0.5,
            optimise=OptimisationMetric.RETENTION,
        )
        framework.create_experiment(exp)
        # Treatment escalates much less — should win on retention.
        for i in range(200):
            framework.record_outcome(
                exp.name,
                "control",
                guard_result=_passthrough_verdict(),
                escalated=(i < 100),  # 50% escalation
                latency_ms=100.0,
            )
            framework.record_outcome(
                exp.name,
                "treatment",
                guard_result=_passthrough_verdict(),
                escalated=(i < 10),  # 5% escalation
                latency_ms=100.0,
            )
        result = framework.analyse(exp.name)
        assert result.optimise is OptimisationMetric.RETENTION
        assert result.winner == "treatment"
        assert result.p_value < 0.05

    def test_latency_metric_lower_is_better(
        self, framework: ABTestingFramework
    ) -> None:
        exp = Experiment(
            name="latency-exp",
            control_model="azure",
            treatment_model="anthropic",
            traffic_split=0.5,
            optimise=OptimisationMetric.LATENCY,
        )
        framework.create_experiment(exp)
        for _ in range(100):
            framework.record_outcome(
                exp.name,
                "control",
                guard_result=_passthrough_verdict(),
                escalated=False,
                latency_ms=500.0,
            )
            framework.record_outcome(
                exp.name,
                "treatment",
                guard_result=_passthrough_verdict(),
                escalated=False,
                latency_ms=200.0,
            )
        result = framework.analyse(exp.name)
        assert result.optimise is OptimisationMetric.LATENCY
        assert result.winner == "treatment"
        assert result.effect_size < 0  # treatment is faster
        assert "latency" in result.rationale.lower()

    def test_result_is_pure_value_object(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        """ExperimentResult is frozen — sign-off snapshots must not drift."""
        _seed_arm(
            registered_framework, basic_experiment.name, "control", n=40, successes=30
        )
        _seed_arm(
            registered_framework, basic_experiment.name, "treatment", n=40, successes=35
        )
        result = registered_framework.analyse(basic_experiment.name)
        assert isinstance(result, ExperimentResult)
        with pytest.raises((AttributeError, TypeError, ValueError)):
            result.winner = "control"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_snapshot_shape(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        snap = registered_framework.snapshot(basic_experiment.name)
        assert snap["experiment"] == basic_experiment.name
        assert snap["status"] == "running"
        assert snap["control_model"] == basic_experiment.control_model
        assert snap["treatment_model"] == basic_experiment.treatment_model
        assert snap["traffic_split"] == basic_experiment.traffic_split
        assert snap["optimise"] == basic_experiment.optimise.value
        assert "control" in snap
        assert "treatment" in snap

    def test_snapshot_unknown_raises(self, framework: ABTestingFramework) -> None:
        with pytest.raises(UnknownExperimentError):
            framework.snapshot("ghost")

    def test_snapshot_does_not_alias_live_state(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        """Mutating the returned dict must not corrupt internal counters."""
        snap = registered_framework.snapshot(basic_experiment.name)
        snap["control"]["samples"] = 999_999.0
        snap2 = registered_framework.snapshot(basic_experiment.name)
        assert snap2["control"]["samples"] == 0.0


# ---------------------------------------------------------------------------
# Full pipeline (Customer query → route → record → analyse)
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """Customer-facing flow: Bridge picks a model, records the outcome, reports."""

    def test_end_to_end_with_winner(self, framework: ABTestingFramework) -> None:
        exp = Experiment(
            name="e2e-pipeline",
            control_model="azure",
            treatment_model="anthropic",
            traffic_split=0.5,
        )
        framework.create_experiment(exp)

        # Simulate 400 customer sessions flowing through the pipeline.
        for i in range(400):
            session_id = f"customer-{i}"
            assignment = framework.route_traffic(exp.name, session_id, query="Saldo?")
            # Mocked "LLM call": treatment is more accurate (90% vs 60%).
            if assignment.variant == "treatment":
                verdict = _passthrough_verdict() if i % 10 != 0 else _abstain_verdict()
                escalated = i % 10 == 0
            else:
                verdict = _passthrough_verdict() if i % 5 < 3 else _abstain_verdict()
                escalated = i % 5 >= 3
            framework.record_outcome(
                exp.name,
                assignment.variant,
                guard_result=verdict,
                escalated=escalated,
                latency_ms=150.0,
                confidence=0.85,
            )

        result = framework.analyse(exp.name)
        assert result.samples_control + result.samples_treatment == 400
        assert result.winner == "treatment"
        assert result.p_value < 0.05

    def test_pipeline_preserves_session_routing(
        self, framework: ABTestingFramework
    ) -> None:
        """Re-querying the same customer hits the same model on every turn."""
        exp = Experiment(
            name="session-stable",
            control_model="azure",
            treatment_model="anthropic",
            traffic_split=0.5,
        )
        framework.create_experiment(exp)
        seen: dict[str, str] = {}
        for turn in range(10):
            for cust in ["cust-A", "cust-B", "cust-C"]:
                assn = framework.route_traffic(exp.name, cust)
                if turn == 0:
                    seen[cust] = assn.model_id
                else:
                    assert assn.model_id == seen[cust]

    def test_low_confidence_outcomes_drag_accuracy_down(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        """ABSTAIN verdicts (low confidence → escalate) must lower the metric."""
        for _ in range(50):
            registered_framework.record_outcome(
                basic_experiment.name,
                "control",
                guard_result=_abstain_verdict(),
                escalated=True,
                latency_ms=120.0,
                confidence=0.2,
            )
        snap = registered_framework.snapshot(basic_experiment.name)
        assert snap["control"]["accuracy"] == 0.0
        assert snap["control"]["retention"] == 0.0

    def test_pii_query_text_not_stored_in_counters(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        """Even when the operator passes raw PII as ``query``, no counter holds it."""
        pii_query = "Meu CPF é 123.456.789-00, qual meu saldo?"
        assignment = registered_framework.route_traffic(
            basic_experiment.name, "session-pii", query=pii_query
        )
        registered_framework.record_outcome(
            basic_experiment.name,
            assignment.variant,
            guard_result=_passthrough_verdict(),
            escalated=False,
            latency_ms=100.0,
        )
        snap = registered_framework.snapshot(basic_experiment.name)
        # The query never leaks into the counters/snapshot.
        for value in snap.values():
            assert "123.456.789-00" not in str(value)


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_record_outcomes_no_lost_updates(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        """Bridge serves concurrent traffic — counters must not race."""
        per_thread = 200
        threads_per_arm = 4

        def worker(variant: str) -> None:
            for _ in range(per_thread):
                registered_framework.record_outcome(
                    basic_experiment.name,
                    variant,
                    guard_result=_passthrough_verdict(),
                    escalated=False,
                    latency_ms=100.0,
                )

        threads = [
            threading.Thread(target=worker, args=(variant,))
            for variant in ("control", "treatment")
            for _ in range(threads_per_arm)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = registered_framework.snapshot(basic_experiment.name)
        expected = per_thread * threads_per_arm
        assert snap["control"]["samples"] == float(expected)
        assert snap["treatment"]["samples"] == float(expected)


# ---------------------------------------------------------------------------
# VariantMetrics (counter object)
# ---------------------------------------------------------------------------


class TestVariantMetrics:
    def test_zero_samples_gives_zero_metrics(self) -> None:
        m = VariantMetrics()
        assert m.accuracy() == 0.0
        assert m.retention() == 0.0
        assert m.avg_latency_ms() == 0.0
        assert m.avg_confidence() == 0.0

    def test_snapshot_returns_plain_floats(self) -> None:
        m = VariantMetrics(
            samples=10,
            passthrough=8,
            retained=9,
            total_latency_ms=500.0,
            total_confidence=8.0,
            confidence_samples=10,
        )
        snap = m.snapshot()
        assert snap["samples"] == 10.0
        assert snap["accuracy"] == 0.8
        assert snap["retention"] == 0.9
        assert snap["avg_latency_ms"] == 50.0
        assert snap["avg_confidence"] == 0.8


# ---------------------------------------------------------------------------
# Stateless helpers
# ---------------------------------------------------------------------------


class TestDecisionPassthrough:
    def test_none_verdict_is_false(self) -> None:
        assert _decision_passthrough(None) is False

    def test_passthrough_via_policy_outcome(self) -> None:
        verdict = SimpleNamespace(
            policy_outcome=SimpleNamespace(decision=PolicyDecision.PASSTHROUGH)
        )
        assert _decision_passthrough(verdict) is True

    def test_passthrough_via_top_level_decision(self) -> None:
        verdict = SimpleNamespace(decision=PolicyDecision.PASSTHROUGH)
        assert _decision_passthrough(verdict) is True

    @pytest.mark.parametrize(
        "decision",
        [PolicyDecision.ABSTAIN, PolicyDecision.FLAG, PolicyDecision.RAISE],
    )
    def test_non_passthrough_is_false(self, decision: PolicyDecision) -> None:
        verdict = SimpleNamespace(policy_outcome=SimpleNamespace(decision=decision))
        assert _decision_passthrough(verdict) is False


class TestStatsHelpers:
    def test_standard_normal_cdf_known_values(self) -> None:
        assert _standard_normal_cdf(0.0) == pytest.approx(0.5, abs=1e-9)
        assert _standard_normal_cdf(1.96) == pytest.approx(0.975, abs=1e-3)
        assert _standard_normal_cdf(-1.96) == pytest.approx(0.025, abs=1e-3)

    def test_z_test_degenerate_inputs(self) -> None:
        assert _two_proportion_z_test(0, 0, 0, 0) == (1.0, 0.0)
        assert _two_proportion_z_test(0, 100, 0, 100) == (1.0, 0.0)
        assert _two_proportion_z_test(100, 100, 100, 100) == (1.0, 0.0)

    def test_z_test_significant_difference(self) -> None:
        p_value, z = _two_proportion_z_test(60, 100, 90, 100)
        assert p_value < 0.05
        assert z > 0

    def test_z_test_no_difference(self) -> None:
        p_value, z = _two_proportion_z_test(50, 100, 51, 100)
        assert p_value > 0.5
        assert abs(z) < 1.0

    def test_welch_t_degenerate(self) -> None:
        assert _welch_t_test_from_means(100.0, 1, 100.0, 1) == (1.0, 0.0)
        assert _welch_t_test_from_means(0.0, 100, 0.0, 100) == (1.0, 0.0)

    def test_welch_t_detects_clear_gap(self) -> None:
        p_value, _t = _welch_t_test_from_means(500.0, 200, 200.0, 200)
        assert p_value < 0.05


class TestPickWinner:
    def test_high_p_value_is_inconclusive(self) -> None:
        assert _pick_winner(0.5, 0.2, prefer_higher=True) == "inconclusive"

    def test_positive_effect_prefer_higher(self) -> None:
        assert _pick_winner(0.1, 0.01, prefer_higher=True) == "treatment"

    def test_negative_effect_prefer_higher(self) -> None:
        assert _pick_winner(-0.1, 0.01, prefer_higher=True) == "control"

    def test_alpha_boundary(self) -> None:
        """p exactly at 0.05 should still be significant (the gate is > 0.05)."""
        assert _pick_winner(0.1, 0.05, prefer_higher=True) == "treatment"


# ---------------------------------------------------------------------------
# Backwards-compat alias
# ---------------------------------------------------------------------------


class TestAnalyseAlias:
    def test_analyze_is_alias_for_analyse(
        self, registered_framework: ABTestingFramework, basic_experiment: Experiment
    ) -> None:
        _seed_arm(
            registered_framework, basic_experiment.name, "control", n=40, successes=20
        )
        _seed_arm(
            registered_framework, basic_experiment.name, "treatment", n=40, successes=20
        )
        a = registered_framework.analyse(basic_experiment.name)
        b = registered_framework.analyze(basic_experiment.name)
        assert a.winner == b.winner
        assert a.p_value == pytest.approx(b.p_value)
        assert a.effect_size == pytest.approx(b.effect_size)
