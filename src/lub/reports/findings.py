# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""OCC 2011-12 / SR 11-7 findings-vs-observations taxonomy.

Model-risk-management (MRM) review language distinguishes two levels of
severity for validation results:

- **Finding** — a material deviation from expected performance that
  requires remediation before the model is cleared for production. In
  SR 11-7 terms, a calibration error or fairness gap large enough to
  affect downstream decisions.
- **Observation** — a non-material note: something the reviewer wants
  the development team to be aware of but that does not block approval.

This module provides :class:`FindingClassifier` that labels each metric
value on a :class:`~lub.types.BenchmarkResult` as one of
:class:`Severity.FINDING`, :class:`Severity.OBSERVATION`, or
:class:`Severity.PASS` based on configurable thresholds. The L5 report
surfaces the label next to every metric row so the MRM team can triage
at a glance, matching the Zest Model Management / OCC 2011-12
narrative convention.

No external dependency; pure stdlib + the dataclasses in
:mod:`lub.types`. Default thresholds come from common banking-model-
validation heuristics (ECE ≤ 0.05, AUROC ≥ 0.7), overridable by the
caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from lub.types import BenchmarkResult


class Severity(StrEnum):
    """Three-level MRM severity classification.

    Ordered worst → best: ``FINDING`` blocks approval, ``OBSERVATION``
    flags for follow-up, ``PASS`` clears the metric.
    """

    FINDING = "finding"
    OBSERVATION = "observation"
    PASS = "pass"


@dataclass(frozen=True)
class MetricThreshold:
    """Per-metric thresholds separating PASS / OBSERVATION / FINDING.

    Interpretation depends on ``higher_is_better``:

    - If ``True``: value ≥ ``observation`` = PASS; ``finding`` ≤ v < ``observation`` = OBSERVATION; v < ``finding`` = FINDING.
    - If ``False``: value ≤ ``observation`` = PASS; ``observation`` < v ≤ ``finding`` = OBSERVATION; v > ``finding`` = FINDING.
    """

    observation: float
    finding: float
    higher_is_better: bool = True

    def classify(self, value: float) -> Severity:
        """Classify metrics against threshold bands."""
        if self.higher_is_better:
            if value >= self.observation:
                return Severity.PASS
            if value >= self.finding:
                return Severity.OBSERVATION
            return Severity.FINDING
        # Lower is better (e.g., ECE, RMSCE, miscalibration_area).
        if value <= self.observation:
            return Severity.PASS
        if value <= self.finding:
            return Severity.OBSERVATION
        return Severity.FINDING


# Defaults derived from common SR 11-7 / OCC 2011-12 model-validation
# heuristics for consumer-credit and regulated-QA models. Deliberately
# conservative — an MRM team can (and should) override per use case.
DEFAULT_THRESHOLDS: dict[str, MetricThreshold] = {
    "accuracy": MetricThreshold(observation=0.70, finding=0.50, higher_is_better=True),
    "refusal_auroc": MetricThreshold(observation=0.70, finding=0.55, higher_is_better=True),
    "prr": MetricThreshold(observation=0.50, finding=0.20, higher_is_better=True),
    "spearman": MetricThreshold(observation=0.30, finding=0.10, higher_is_better=True),
    "kendall_tau": MetricThreshold(observation=0.25, finding=0.08, higher_is_better=True),
    "ece": MetricThreshold(observation=0.05, finding=0.10, higher_is_better=False),
    "rmsce": MetricThreshold(observation=0.07, finding=0.15, higher_is_better=False),
    "brier": MetricThreshold(observation=0.15, finding=0.25, higher_is_better=False),
    "miscalibration_area": MetricThreshold(observation=0.08, finding=0.15, higher_is_better=False),
    "missing_ratio": MetricThreshold(observation=0.20, finding=0.40, higher_is_better=False),
    "reversed_pairs_proportion": MetricThreshold(
        observation=0.30, finding=0.45, higher_is_better=False
    ),
    # Sharpness is a decisiveness diagnostic — we report it but don't
    # gate approval on it in isolation (only meaningful paired with ECE).
    # Both thresholds are pinned at 0.0 so every non-negative sharpness
    # value PASSes; the number still appears in the report for transparency
    # but never produces a FINDING/OBSERVATION on its own. Previous values
    # (obs=0.05, finding=0.01) contradicted the stated "nearly always
    # PASSes" intent for flat-confidence models with sharpness < 0.05.
    "sharpness": MetricThreshold(observation=0.0, finding=0.0, higher_is_better=True),
    "ence": MetricThreshold(observation=0.10, finding=0.20, higher_is_better=False),
    "adversarial_group_calibration": MetricThreshold(
        observation=0.10, finding=0.20, higher_is_better=False
    ),
    "aurc": MetricThreshold(observation=0.15, finding=0.30, higher_is_better=False),
    "auucc": MetricThreshold(observation=0.50, finding=0.30, higher_is_better=True),
    "crps_from_confidence": MetricThreshold(observation=0.15, finding=0.25, higher_is_better=False),
    "negative_log_likelihood": MetricThreshold(
        observation=0.50, finding=1.00, higher_is_better=False
    ),
}


@dataclass(frozen=True)
class ClassifiedMetric:
    """One ``(metric, value, severity)`` triple with the threshold band."""

    name: str
    value: float
    severity: Severity
    threshold: MetricThreshold | None


@dataclass(frozen=True)
class Report:
    """Aggregated MRM triage over one :class:`BenchmarkResult`.

    Summarizes every metric as a :class:`ClassifiedMetric`; convenience
    properties return findings / observations counts so an L5 template
    can print them in the executive summary.
    """

    classified: tuple[ClassifiedMetric, ...]

    @property
    def findings(self) -> tuple[ClassifiedMetric, ...]:
        """Return classified metrics with finding-level severity."""
        return tuple(m for m in self.classified if m.severity is Severity.FINDING)

    @property
    def observations(self) -> tuple[ClassifiedMetric, ...]:
        """Return classified metrics with observation-level severity."""
        return tuple(m for m in self.classified if m.severity is Severity.OBSERVATION)

    @property
    def passes(self) -> tuple[ClassifiedMetric, ...]:
        """Return classified metrics that passed (no severity)."""
        return tuple(m for m in self.classified if m.severity is Severity.PASS)

    @property
    def worst(self) -> Severity:
        """Severity of the worst classified metric (FINDING > OBSERVATION > PASS)."""
        if self.findings:
            return Severity.FINDING
        if self.observations:
            return Severity.OBSERVATION
        return Severity.PASS


@dataclass
class FindingClassifier:
    """Classify BenchmarkResult metrics into OCC 2011-12 severity bands.

    Parameters
    ----------
    thresholds:
        Per-metric threshold definitions.  Defaults to
        :data:`DEFAULT_THRESHOLDS` (SR 11-7 / OCC 2011-12 heuristics).
        Override for domain-specific risk appetites — e.g., tighter ECE
        for credit-risk QA than general regulatory QA.
    unknown_metric_severity:
        Severity assigned to metrics not in ``thresholds``.  Defaults to
        ``PASS`` (reported for transparency but does not block).  Set to
        ``OBSERVATION`` to flag all unregistered metrics for review, or
        ``FINDING`` to fail unknown metrics (strict mode for MRM teams
        that require explicit threshold coverage).
    """

    thresholds: dict[str, MetricThreshold] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    unknown_metric_severity: Severity = Severity.PASS

    def classify(self, result: BenchmarkResult) -> Report:
        """Return a :class:`Report` with every metric in ``result``.

        Metrics without a declared threshold receive
        ``unknown_metric_severity`` (default PASS).
        """
        classified: list[ClassifiedMetric] = []
        for name, value in sorted(result.metrics.items()):
            th = self.thresholds.get(name)
            severity = th.classify(value) if th else self.unknown_metric_severity
            classified.append(
                ClassifiedMetric(name=name, value=value, severity=severity, threshold=th)
            )
        return Report(classified=tuple(classified))


__all__ = [
    "ClassifiedMetric",
    "DEFAULT_THRESHOLDS",
    "FindingClassifier",
    "MetricThreshold",
    "Report",
    "Severity",
]
