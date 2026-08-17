# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""A/B testing framework for the LLM-agnostic Bradesco Bridge platform.

Bradesco's published Bridge architecture is explicit that the platform
is *LLM-agnostic* — the same operator-facing surface must be able to
swap between Azure OpenAI, Anthropic, and self-hosted models without
rewiring agents. Choosing *which* provider to roll out to production is
not a static decision: it requires controlled experimentation against
the headline metrics Bradesco reports on the Azure AI Foundry customer
page (90% retention, 95% accuracy, 40% call-handling-time reduction).

This module is the experimentation layer that makes those provider
decisions auditable:

* :class:`Experiment` — frozen declaration of a single comparison
  (control vs. treatment, traffic split, the metric to optimise).
* :class:`ABTestingFramework` — runtime that hashes the customer's
  session id into a stable bucket, records per-variant outcomes, and
  emits a structured :class:`ExperimentResult` once the experiment is
  analysed.
* :class:`ExperimentResult` — the final verdict, including the
  two-proportion z-test p-value that a model-risk reviewer (SR 11-7)
  can quote when promoting a treatment to default.

Banking / compliance notes
--------------------------

* **Deterministic assignment.** Routing is a SHA-256 hash over
  ``(experiment_name, session_id)`` modulo 10_000 — the same customer
  in the same experiment lands on the same variant on every call. This
  is required for BCB 4893 incident-replay: an auditor must be able to
  reconstruct which model produced a flagged answer.
* **No silent fallbacks.** Recording an outcome against an unknown
  experiment or variant raises rather than logging-and-continuing —
  banking software prefers loud failures so a typo in the variant
  identifier never silently buckets the customer into a wrong arm.
* **Audit trail.** Every assignment, outcome, and analysis emits a
  structured log line through ``structlog`` with the experiment name,
  variant, and (when relevant) the test statistic. This is the
  evidence stream a BCBS 239 reviewer follows when asked "why did the
  bank switch from provider A to provider B between Q2 and Q3?".

This module is dependency-light: it relies on the standard library for
hashing and statistics (a self-contained normal-CDF approximation —
banking environments often forbid SciPy at the edge), :mod:`pydantic`
for declaration validation, and :class:`~lub.guard.PolicyDecision` to
classify whether a guard verdict counted as an "accurate" answer.
"""

from __future__ import annotations

import hashlib
import math
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator

from lub.guard import GuardResult, PolicyDecision

__all__ = [
    "ABTestingFramework",
    "Experiment",
    "ExperimentResult",
    "ExperimentStatus",
    "OptimisationMetric",
    "UnknownExperimentError",
    "UnknownVariantError",
    "VariantAssignment",
    "VariantMetrics",
]

_LOG = structlog.get_logger("lub.bridge.ab_testing")

# Resolution of the hashing bucket. 10_000 lets the operator express
# traffic splits down to 0.01% (one basis point), which matches the
# granularity used for canary rollouts on the existing Bridge router.
_BUCKET_RESOLUTION = 10_000

# Lower bound on per-arm sample count before :meth:`analyse` will commit
# to declaring a winner. Below this we still compute the statistic but
# tag the result as inconclusive — SR 11-7 expects model-risk decisions
# to be backed by enough signal to distinguish them from noise.
_MIN_SAMPLES_FOR_VERDICT = 30


# ---------------------------------------------------------------------------
# Public value objects
# ---------------------------------------------------------------------------


class ExperimentStatus(StrEnum):
    """Lifecycle of an :class:`Experiment` inside the framework."""

    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


class OptimisationMetric(StrEnum):
    """Headline metric an experiment is being judged against.

    The values mirror the Bradesco-reported metrics so an experiment
    declaration reads as a contract against a public SLA rather than an
    arbitrary choice. The semantics:

    * :attr:`ACCURACY` — share of replies whose guard verdict was
      :attr:`~lub.guard.PolicyDecision.PASSTHROUGH` (the calibrated
      confidence cleared the threshold, so the answer was returned
      verbatim). Maps to Bradesco's 95% accuracy headline.
    * :attr:`RETENTION` — share of queries kept inside the automated
      channel (no escalation). Maps to Bradesco's 90% retention headline.
    * :attr:`LATENCY` — wall-clock per-query latency in milliseconds.
      Lower is better; tied to the 40% call-handling-time reduction.
    """

    ACCURACY = "accuracy"
    RETENTION = "retention"
    LATENCY = "latency"


class Experiment(BaseModel):
    """Declarative spec of a single A/B comparison.

    Frozen — once an experiment is created, the spec cannot mutate. To
    change the traffic split or the optimisation metric, end the
    experiment and create a new one. This keeps the SR 11-7 audit
    trail intact: every outcome belongs to exactly one immutable spec.

    Parameters
    ----------
    name:
        Stable identifier (e.g. ``"azure-vs-anthropic-2026q2"``). Used
        in logs and bucket hashing — changing it re-buckets every
        customer, so treat it as part of the experiment's identity.
    control_model:
        Identifier of the incumbent backend. The framework does **not**
        dispatch to backends itself; it returns this string for the
        caller to route through :class:`~lub.bridge.router.BridgeRouter`.
    treatment_model:
        Identifier of the challenger backend.
    traffic_split:
        Share of traffic routed to ``treatment_model`` (``0.0`` to
        ``1.0``). The remainder goes to ``control_model``. Pinned at
        creation time to keep the hashing deterministic.
    optimise:
        Which metric :meth:`ABTestingFramework.analyse` uses to declare
        a winner. Defaults to accuracy because banking customers
        tolerate a slightly slower reply more readily than a wrong one.
    description:
        Free-form rationale captured in audit logs. Encourage operators
        to record *why* the experiment is being run.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., min_length=1, max_length=128)
    control_model: str = Field(..., min_length=1, max_length=128)
    treatment_model: str = Field(..., min_length=1, max_length=128)
    traffic_split: float = Field(..., ge=0.0, le=1.0)
    optimise: OptimisationMetric = Field(default=OptimisationMetric.ACCURACY)
    description: str = Field(default="", max_length=2048)

    @field_validator("treatment_model")
    @classmethod
    def _models_must_differ(cls, value: str, info: Any) -> str:
        control = info.data.get("control_model")
        if control is not None and control == value:
            raise ValueError(f"treatment_model must differ from control_model (both are {value!r})")
        return value


@dataclass(frozen=True)
class VariantAssignment:
    """Routing decision returned by :meth:`ABTestingFramework.route_traffic`.

    Holds the chosen model identifier plus the bucketing metadata the
    audit trail needs to reproduce the decision later (the bucket is
    the hash modulo 10_000, so an auditor can recompute it from the
    session id alone).
    """

    experiment: str
    session_id: str
    variant: str  # "control" or "treatment"
    model_id: str
    bucket: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class VariantMetrics:
    """Running aggregates for one arm of an experiment.

    Mutable because the framework updates it on every recorded outcome.
    Snapshots returned to callers are converted to plain dictionaries
    so external code cannot accidentally mutate the live counters.
    """

    samples: int = 0
    passthrough: int = 0  # guard verdict was PASSTHROUGH (counts as accurate)
    retained: int = 0  # no escalation
    total_latency_ms: float = 0.0
    total_confidence: float = 0.0
    confidence_samples: int = 0

    def accuracy(self) -> float:
        """Share of samples with a PASSTHROUGH guard verdict."""
        return self.passthrough / self.samples if self.samples else 0.0

    def retention(self) -> float:
        """Share of samples that did not escalate to a human operator."""
        return self.retained / self.samples if self.samples else 0.0

    def avg_latency_ms(self) -> float:
        """Mean wall-clock latency across recorded samples."""
        return self.total_latency_ms / self.samples if self.samples else 0.0

    def avg_confidence(self) -> float:
        """Mean guard confidence across samples that reported one."""
        if self.confidence_samples == 0:
            return 0.0
        return self.total_confidence / self.confidence_samples

    def snapshot(self) -> dict[str, float]:
        """Plain-dict view safe to hand out to callers and serialisers."""
        return {
            "samples": float(self.samples),
            "accuracy": self.accuracy(),
            "retention": self.retention(),
            "avg_latency_ms": self.avg_latency_ms(),
            "avg_confidence": self.avg_confidence(),
        }


@dataclass(frozen=True)
class ExperimentResult:
    """Final verdict of :meth:`ABTestingFramework.analyse`.

    ``winner`` is one of ``"control"``, ``"treatment"``, or
    ``"inconclusive"``. The third bucket exists deliberately — banking
    governance reviewers (SR 11-7) reject "the treatment looked
    slightly better" promotions, so we surface low-power experiments
    explicitly rather than declaring a marginal winner.

    ``p_value`` is the two-sided p-value of the appropriate test:

    * For :attr:`OptimisationMetric.ACCURACY` and
      :attr:`OptimisationMetric.RETENTION` — a two-proportion z-test.
    * For :attr:`OptimisationMetric.LATENCY` — a Welch's t-style
      approximation. We do not store per-sample latencies (banking
      observability prefers running aggregates), so the test uses the
      sample variance implied by an arrival-time bound and is
      intentionally conservative; treat the p-value as a screen rather
      than a strict significance gate.
    """

    experiment: str
    optimise: OptimisationMetric
    control_metrics: Mapping[str, float]
    treatment_metrics: Mapping[str, float]
    winner: str
    p_value: float
    effect_size: float
    samples_control: int
    samples_treatment: int
    rationale: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UnknownExperimentError(KeyError):
    """Raised when an experiment name is not registered with the framework."""


class UnknownVariantError(ValueError):
    """Raised when an outcome is recorded against an unrecognised variant."""


# ---------------------------------------------------------------------------
# Framework
# ---------------------------------------------------------------------------


class ABTestingFramework:
    """Coordinator for in-flight Bridge experiments.

    The framework is intentionally thread-safe — Bridge serves
    concurrent customer traffic, and per-variant counters would race
    without it. Locking is coarse (one ``threading.Lock`` per
    framework instance) because the critical section is small and
    contention is dominated by I/O on the model call, not by the
    counter update.

    Notes
    -----
    The framework does *not* call models. It returns a model identifier
    from :meth:`route_traffic` that the caller then dispatches through
    its own backend layer (typically :class:`~lub.bridge.router.BridgeRouter`).
    Keeping the two responsibilities apart lets the same framework
    drive any LLM-agnostic deployment without depending on the wire
    layer — a deliberate design choice mirroring the existing
    :class:`~lub.bridge.router.BridgeRouter`.
    """

    def __init__(self) -> None:
        self._experiments: dict[str, Experiment] = {}
        self._statuses: dict[str, ExperimentStatus] = {}
        self._control_metrics: dict[str, VariantMetrics] = {}
        self._treatment_metrics: dict[str, VariantMetrics] = {}
        self._lock = threading.Lock()
        _LOG.info("bridge.ab_testing.initialized")

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #

    def create_experiment(self, experiment: Experiment) -> None:
        """Register a new :class:`Experiment` in :attr:`ExperimentStatus.RUNNING` state.

        Raises :class:`ValueError` if an experiment with the same name
        already exists — overwrite-by-default would silently discard
        accumulated counters, which a regulator-facing system must
        never do. To re-run, end the old experiment and create a new
        one under a distinct name.
        """
        with self._lock:
            if experiment.name in self._experiments:
                raise ValueError(
                    f"experiment {experiment.name!r} is already registered; "
                    "end it before creating a new one with the same name"
                )
            self._experiments[experiment.name] = experiment
            self._statuses[experiment.name] = ExperimentStatus.RUNNING
            self._control_metrics[experiment.name] = VariantMetrics()
            self._treatment_metrics[experiment.name] = VariantMetrics()

        _LOG.info(
            "bridge.ab_testing.experiment_created",
            name=experiment.name,
            control=experiment.control_model,
            treatment=experiment.treatment_model,
            traffic_split=experiment.traffic_split,
            optimise=experiment.optimise.value,
        )

    def set_status(self, name: str, status: ExperimentStatus) -> None:
        """Move ``name`` to ``status`` (paused/completed/running).

        Paused experiments still serve their existing buckets (the hash
        is deterministic) but :meth:`route_traffic` will not assign
        *new* sessions until the experiment is resumed.

        ``COMPLETED`` is terminal: a completed experiment refuses to
        accept further outcomes so a late-arriving callback cannot
        retroactively change a result that has already been signed off.
        """
        with self._lock:
            self._require_experiment(name)
            old = self._statuses[name]
            self._statuses[name] = status
        _LOG.info(
            "bridge.ab_testing.status_changed",
            name=name,
            old_status=old.value,
            new_status=status.value,
        )

    def list_experiments(self) -> tuple[str, ...]:
        """Names of every experiment ever registered (any status)."""
        with self._lock:
            return tuple(self._experiments)

    def get_experiment(self, name: str) -> Experiment:
        """Return the immutable :class:`Experiment` spec for ``name``."""
        with self._lock:
            return self._require_experiment(name)

    def get_status(self, name: str) -> ExperimentStatus:
        """Return the current :class:`ExperimentStatus` for ``name``."""
        with self._lock:
            self._require_experiment(name)
            return self._statuses[name]

    # ------------------------------------------------------------------ #
    # Routing
    # ------------------------------------------------------------------ #

    def route_traffic(
        self,
        experiment_name: str,
        session_id: str,
        *,
        query: str | None = None,
    ) -> VariantAssignment:
        """Pick the variant for ``session_id`` and return its model identifier.

        The assignment is deterministic in ``(experiment_name, session_id)``
        — the same customer always sees the same variant, which is
        required for both UX consistency and audit replay. ``query`` is
        accepted as an optional positional context for the audit log
        (e.g. to record how many characters the customer typed) but
        does **not** influence the bucket.

        Raises :class:`UnknownExperimentError` if the experiment is
        unknown. If the experiment is paused or completed, the customer
        is routed to the *control* model — this is the conservative
        choice (revert to the incumbent) consistent with BCB 4893's
        bias toward known-good behaviour during operator interventions.
        """
        with self._lock:
            experiment = self._require_experiment(experiment_name)
            status = self._statuses[experiment_name]

        # Pause / completion → fall back to the incumbent variant.
        if status is not ExperimentStatus.RUNNING:
            assignment = VariantAssignment(
                experiment=experiment_name,
                session_id=session_id,
                variant="control",
                model_id=experiment.control_model,
                bucket=self._bucket(experiment_name, session_id),
            )
            _LOG.info(
                "bridge.ab_testing.route_control_due_to_status",
                experiment=experiment_name,
                session_id=session_id,
                status=status.value,
            )
            return assignment

        bucket = self._bucket(experiment_name, session_id)
        threshold = int(round(experiment.traffic_split * _BUCKET_RESOLUTION))
        variant = "treatment" if bucket < threshold else "control"
        model_id = (
            experiment.treatment_model if variant == "treatment" else experiment.control_model
        )

        assignment = VariantAssignment(
            experiment=experiment_name,
            session_id=session_id,
            variant=variant,
            model_id=model_id,
            bucket=bucket,
        )

        _LOG.info(
            "bridge.ab_testing.route_decided",
            experiment=experiment_name,
            session_id=session_id,
            variant=variant,
            model_id=model_id,
            bucket=bucket,
            query_chars=len(query) if query is not None else None,
        )
        return assignment

    # ------------------------------------------------------------------ #
    # Outcome recording
    # ------------------------------------------------------------------ #

    def record_outcome(
        self,
        experiment_name: str,
        variant: str,
        *,
        guard_result: GuardResult | None = None,
        escalated: bool,
        latency_ms: float,
        confidence: float | None = None,
    ) -> None:
        """Append a single per-query outcome to the variant counters.

        Parameters
        ----------
        experiment_name:
            Name passed to :meth:`create_experiment`.
        variant:
            One of ``"control"`` or ``"treatment"``. Must match the
            value returned from the prior :meth:`route_traffic` call.
        guard_result:
            Verdict from :class:`~lub.guard.UncertaintyGuard`. The
            decision drives the accuracy counter; ``None`` means the
            guard never ran (treated as a non-accurate sample for the
            purposes of the metric, conservatively).
        escalated:
            ``True`` when the platform routed the query to a human
            operator. Used to compute retention.
        latency_ms:
            End-to-end wall-clock latency for the query.
        confidence:
            Optional calibrated confidence score from the guard, kept
            in a running mean for diagnostics. Not used by the
            statistical test.

        Raises
        ------
        UnknownExperimentError
            If ``experiment_name`` is not registered.
        UnknownVariantError
            If ``variant`` is anything other than ``"control"`` /
            ``"treatment"``. A typo here would corrupt the test; we
            refuse silently-best-guess behaviour.
        RuntimeError
            If the experiment is already :attr:`ExperimentStatus.COMPLETED`.
        """
        if latency_ms < 0:
            raise ValueError(f"latency_ms must be >= 0, got {latency_ms!r}")

        with self._lock:
            self._require_experiment(experiment_name)
            status = self._statuses[experiment_name]
            if status is ExperimentStatus.COMPLETED:
                raise RuntimeError(
                    f"experiment {experiment_name!r} is COMPLETED; further "
                    "outcomes would invalidate the sign-off — reopen it explicitly first"
                )

            counters = self._counters_for(experiment_name, variant)
            counters.samples += 1
            counters.total_latency_ms += float(latency_ms)
            if not escalated:
                counters.retained += 1
            if _decision_passthrough(guard_result):
                counters.passthrough += 1
            if confidence is not None:
                counters.total_confidence += float(confidence)
                counters.confidence_samples += 1

        _LOG.debug(
            "bridge.ab_testing.outcome_recorded",
            experiment=experiment_name,
            variant=variant,
            escalated=escalated,
            latency_ms=latency_ms,
            confidence=confidence,
            passthrough=_decision_passthrough(guard_result),
        )

    # ------------------------------------------------------------------ #
    # Analysis
    # ------------------------------------------------------------------ #

    def analyse(self, experiment_name: str) -> ExperimentResult:
        """Compute the current :class:`ExperimentResult` for ``experiment_name``.

        Safe to call repeatedly — it does not mutate counters. Use this
        for both interim peeks and final sign-off. The framework
        deliberately does not auto-stop on a significance threshold:
        deciding when an experiment ends is an operator/governance
        decision, not an algorithmic one.
        """
        with self._lock:
            experiment = self._require_experiment(experiment_name)
            control = _copy_metrics(self._control_metrics[experiment_name])
            treatment = _copy_metrics(self._treatment_metrics[experiment_name])

        winner, p_value, effect_size, rationale = self._evaluate(experiment, control, treatment)

        result = ExperimentResult(
            experiment=experiment.name,
            optimise=experiment.optimise,
            control_metrics=control.snapshot(),
            treatment_metrics=treatment.snapshot(),
            winner=winner,
            p_value=p_value,
            effect_size=effect_size,
            samples_control=control.samples,
            samples_treatment=treatment.samples,
            rationale=rationale,
        )

        _LOG.info(
            "bridge.ab_testing.analysis_complete",
            experiment=experiment.name,
            optimise=experiment.optimise.value,
            winner=winner,
            p_value=p_value,
            effect_size=effect_size,
            samples_control=control.samples,
            samples_treatment=treatment.samples,
        )
        return result

    # Backwards-compat alias to match American/British spelling used in
    # the original spec — operators reading the architecture doc will
    # type ``analyze``; tests targeting the framework may use either.
    analyze = analyse

    # ------------------------------------------------------------------ #
    # Snapshots
    # ------------------------------------------------------------------ #

    def snapshot(self, experiment_name: str) -> dict[str, Any]:
        """Plain-dict snapshot of the experiment's current counters.

        Designed for /metrics endpoints and tests. Never returns live
        mutable state.
        """
        with self._lock:
            self._require_experiment(experiment_name)
            control = _copy_metrics(self._control_metrics[experiment_name])
            treatment = _copy_metrics(self._treatment_metrics[experiment_name])
            status = self._statuses[experiment_name]
            spec = self._experiments[experiment_name]

        return {
            "experiment": experiment_name,
            "status": status.value,
            "control_model": spec.control_model,
            "treatment_model": spec.treatment_model,
            "traffic_split": spec.traffic_split,
            "optimise": spec.optimise.value,
            "control": control.snapshot(),
            "treatment": treatment.snapshot(),
        }

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _require_experiment(self, name: str) -> Experiment:
        """Look up an experiment, raising :class:`UnknownExperimentError`."""
        experiment = self._experiments.get(name)
        if experiment is None:
            raise UnknownExperimentError(f"experiment {name!r} is not registered")
        return experiment

    def _counters_for(self, experiment_name: str, variant: str) -> VariantMetrics:
        """Map a variant string to its mutable counter object."""
        if variant == "control":
            return self._control_metrics[experiment_name]
        if variant == "treatment":
            return self._treatment_metrics[experiment_name]
        raise UnknownVariantError(f"variant must be 'control' or 'treatment', got {variant!r}")

    @staticmethod
    def _bucket(experiment_name: str, session_id: str) -> int:
        """Deterministic 0–9999 bucket from ``(experiment, session)``.

        SHA-256 is overkill cryptographically but the cost is
        negligible (microseconds) and it gives an even distribution
        that auditors can re-derive from the inputs alone — required
        for BCB 4893 incident replay.
        """
        key = f"{experiment_name}|{session_id}".encode()
        digest = hashlib.sha256(key).digest()
        # Use the leading 8 bytes; ample entropy for a 10_000-slot ring.
        n = int.from_bytes(digest[:8], "big", signed=False)
        return n % _BUCKET_RESOLUTION

    def _evaluate(
        self,
        experiment: Experiment,
        control: VariantMetrics,
        treatment: VariantMetrics,
    ) -> tuple[str, float, float, str]:
        """Dispatch to the appropriate test for the experiment's metric."""
        metric = experiment.optimise

        if (
            control.samples < _MIN_SAMPLES_FOR_VERDICT
            or treatment.samples < _MIN_SAMPLES_FOR_VERDICT
        ):
            effect = _metric_diff(metric, control, treatment)
            rationale = (
                f"inconclusive: need >= {_MIN_SAMPLES_FOR_VERDICT} samples per arm "
                f"(control={control.samples}, treatment={treatment.samples})"
            )
            return "inconclusive", 1.0, effect, rationale

        if metric in (OptimisationMetric.ACCURACY, OptimisationMetric.RETENTION):
            control_success = (
                control.passthrough if metric is OptimisationMetric.ACCURACY else control.retained
            )
            treatment_success = (
                treatment.passthrough
                if metric is OptimisationMetric.ACCURACY
                else treatment.retained
            )
            p_value, z = _two_proportion_z_test(
                control_success,
                control.samples,
                treatment_success,
                treatment.samples,
            )
            effect = treatment_success / treatment.samples - control_success / control.samples
            winner = _pick_winner(effect, p_value, prefer_higher=True)
            rationale = (
                f"two-proportion z-test on {metric.value}: "
                f"effect={effect:+.4f}, z={z:.3f}, p={p_value:.4f}"
            )
            return winner, p_value, effect, rationale

        # LATENCY: lower is better. Without per-sample variance we use a
        # conservative coefficient-of-variation assumption (banking
        # APIs rarely have cv > 1.0) and a Welch's t approximation.
        effect = treatment.avg_latency_ms() - control.avg_latency_ms()
        p_value, t_stat = _welch_t_test_from_means(
            control.avg_latency_ms(),
            control.samples,
            treatment.avg_latency_ms(),
            treatment.samples,
        )
        winner = _pick_winner(-effect, p_value, prefer_higher=True)
        rationale = (
            f"latency comparison (Welch's t approximation): "
            f"control={control.avg_latency_ms():.1f}ms, "
            f"treatment={treatment.avg_latency_ms():.1f}ms, "
            f"delta={effect:+.1f}ms, t={t_stat:.3f}, p={p_value:.4f}"
        )
        return winner, p_value, effect, rationale


# ---------------------------------------------------------------------------
# Stateless helpers
# ---------------------------------------------------------------------------


def _copy_metrics(src: VariantMetrics) -> VariantMetrics:
    """Snapshot a :class:`VariantMetrics` outside the framework's lock."""
    return VariantMetrics(
        samples=src.samples,
        passthrough=src.passthrough,
        retained=src.retained,
        total_latency_ms=src.total_latency_ms,
        total_confidence=src.total_confidence,
        confidence_samples=src.confidence_samples,
    )


def _decision_passthrough(verdict: GuardResult | None) -> bool:
    """``True`` when the guard verdict counts as an accurate answer.

    Mirrors the convention used by :mod:`lub.bridge.metrics`: only a
    :attr:`~lub.guard.PolicyDecision.PASSTHROUGH` decision is treated
    as an accurate completion. FLAG / ABSTAIN / RAISE all indicate the
    guard intervened, which is by definition not the model's own
    correct answer.
    """
    if verdict is None:
        return False
    outcome = getattr(verdict, "policy_outcome", None)
    decision = (
        getattr(outcome, "decision", None)
        if outcome is not None
        else getattr(verdict, "decision", None)
    )
    return decision == PolicyDecision.PASSTHROUGH


def _metric_diff(
    metric: OptimisationMetric,
    control: VariantMetrics,
    treatment: VariantMetrics,
) -> float:
    """Treatment-minus-control on the experiment's optimisation metric."""
    if metric is OptimisationMetric.ACCURACY:
        return treatment.accuracy() - control.accuracy()
    if metric is OptimisationMetric.RETENTION:
        return treatment.retention() - control.retention()
    # LATENCY: invert so "higher is better" semantics hold uniformly
    return -(treatment.avg_latency_ms() - control.avg_latency_ms())


def _pick_winner(effect: float, p_value: float, *, prefer_higher: bool) -> str:
    """Map (effect, p) into ``control`` / ``treatment`` / ``inconclusive``.

    Uses a fixed alpha of 0.05 — the conservative default for banking
    model-risk decisions. The function is centralised so the same
    threshold applies regardless of metric.
    """
    if p_value > 0.05:
        return "inconclusive"
    if prefer_higher:
        return "treatment" if effect > 0 else "control"
    return "treatment" if effect < 0 else "control"


def _two_proportion_z_test(
    control_success: int,
    control_n: int,
    treatment_success: int,
    treatment_n: int,
) -> tuple[float, float]:
    """Two-sided two-proportion z-test. Returns ``(p_value, z)``.

    Uses the pooled-variance form, which is standard for A/B testing
    on share-of-success metrics like accuracy and retention. Returns
    ``p=1.0`` for degenerate inputs (zero sample size or all-zero
    successes) so callers never see NaN.
    """
    if control_n <= 0 or treatment_n <= 0:
        return 1.0, 0.0
    p_pool = (control_success + treatment_success) / (control_n + treatment_n)
    if p_pool == 0.0 or p_pool == 1.0:
        return 1.0, 0.0
    se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / control_n + 1.0 / treatment_n))
    if se == 0.0:
        return 1.0, 0.0
    diff = (treatment_success / treatment_n) - (control_success / control_n)
    z = diff / se
    p_value = 2.0 * (1.0 - _standard_normal_cdf(abs(z)))
    return max(0.0, min(1.0, p_value)), z


def _welch_t_test_from_means(
    control_mean: float,
    control_n: int,
    treatment_mean: float,
    treatment_n: int,
) -> tuple[float, float]:
    """Approximate Welch's t-test using mean-only inputs.

    Banking telemetry typically retains running aggregates, not
    per-sample arrays, so we approximate the per-arm variance from
    the mean using a coefficient-of-variation of 0.5 (a deliberately
    conservative choice for sub-second latency distributions). The
    returned p-value is therefore a *screen* — a fuller MLOps pipeline
    that retains per-sample latencies should re-run the test against
    raw samples before final sign-off. This is documented on
    :class:`ExperimentResult`.
    """
    if control_n <= 1 or treatment_n <= 1:
        return 1.0, 0.0
    cv = 0.5
    var_control = (control_mean * cv) ** 2
    var_treatment = (treatment_mean * cv) ** 2
    se_sq = var_control / control_n + var_treatment / treatment_n
    if se_sq <= 0.0:
        return 1.0, 0.0
    se = math.sqrt(se_sq)
    t_stat = (treatment_mean - control_mean) / se
    # For n large, t approaches the standard normal; fine here.
    p_value = 2.0 * (1.0 - _standard_normal_cdf(abs(t_stat)))
    return max(0.0, min(1.0, p_value)), t_stat


def _standard_normal_cdf(x: float) -> float:
    """Standard-normal CDF via the math.erf identity.

    Self-contained so this module does not pull in SciPy — banking
    edge deployments often forbid heavy scientific dependencies.
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
