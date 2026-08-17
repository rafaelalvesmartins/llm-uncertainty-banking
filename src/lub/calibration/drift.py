# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Input-distribution drift and performance-estimation monitoring.

Implements two complementary drift-detection patterns for NIST AI RMF
MEASURE 2.7 (Robustness):

1. **Input drift profiling** (inspired by WhyLabs/whylogs) -- compact
   statistical summaries of confidence-score distributions that can be
   compared across time windows to detect distributional shift.

2. **Confidence-Based Performance Estimation** (inspired by
   NannyML/nannyml CBPE) -- estimates performance degradation under
   drift when ground-truth labels are unavailable, a core banking need
   since production regulatory-QA rarely has immediate labels.

No hard dependency on whylogs or nannyml -- the module ships a
lightweight pure-numpy implementation. Optional integration with the
external libraries is left for a future ``lub[drift]`` extra.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog
from numpy.typing import NDArray

_LOG = structlog.get_logger("lub.calibration.drift")


@dataclass(frozen=True)
class DriftProfile:
    """Compact statistical summary of a confidence-score distribution.

    Analogous to a whylogs ``DatasetProfileView`` but scoped to the
    signals LUB's L3 metrics care about: confidence mean, std, quantiles,
    and a histogram for KL/PSI computation.
    """

    timestamp: str
    n: int
    mean: float
    std: float
    median: float
    q05: float
    q25: float
    q75: float
    q95: float
    histogram_counts: tuple[int, ...]
    histogram_edges: tuple[float, ...]

    @staticmethod
    def from_confidences(
        confidences: NDArray[np.floating[Any]],
        n_bins: int = 20,
        timestamp: str | None = None,
    ) -> DriftProfile:
        """Build a profile from a 1-D array of confidence scores in [0, 1]."""
        arr = np.asarray(confidences, dtype=np.float64).ravel()
        if arr.size == 0:
            raise ValueError("confidences must be non-empty")
        counts, edges = np.histogram(arr, bins=n_bins, range=(0.0, 1.0))
        return DriftProfile(
            timestamp=timestamp or datetime.now(tz=UTC).isoformat(),
            n=int(arr.size),
            mean=float(np.mean(arr)),
            std=float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0,
            median=float(np.median(arr)),
            q05=float(np.quantile(arr, 0.05)),
            q25=float(np.quantile(arr, 0.25)),
            q75=float(np.quantile(arr, 0.75)),
            q95=float(np.quantile(arr, 0.95)),
            histogram_counts=tuple(int(c) for c in counts),
            histogram_edges=tuple(float(e) for e in edges),
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize this record to a plain dictionary for JSON-friendly output."""
        return {
            "timestamp": self.timestamp,
            "n": self.n,
            "mean": self.mean,
            "std": self.std,
            "median": self.median,
            "q05": self.q05,
            "q25": self.q25,
            "q75": self.q75,
            "q95": self.q95,
            "histogram_counts": list(self.histogram_counts),
            "histogram_edges": list(self.histogram_edges),
        }


def population_stability_index(
    reference: DriftProfile,
    current: DriftProfile,
    *,
    epsilon: float = 1e-6,
) -> float:
    """Compute the Population Stability Index (PSI) between two profiles.

    PSI < 0.1 -> no significant drift.
    0.1 <= PSI < 0.25 -> moderate drift, investigate.
    PSI >= 0.25 -> significant drift, action required.

    These thresholds are standard in banking model-risk management
    (OCC Bulletin 2011-12).
    """
    ref_counts = np.array(reference.histogram_counts, dtype=np.float64)
    cur_counts = np.array(current.histogram_counts, dtype=np.float64)
    if ref_counts.shape != cur_counts.shape:
        raise ValueError(
            f"profiles must have the same number of bins; "
            f"reference has {ref_counts.shape[0]} bins, current has {cur_counts.shape[0]}"
        )

    ref_pct = ref_counts / ref_counts.sum() + epsilon
    cur_pct = cur_counts / cur_counts.sum() + epsilon
    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


@dataclass(frozen=True)
class DriftThresholds:
    """Configurable PSI thresholds for drift severity classification.

    Defaults follow OCC 2011-12 (Supervisory Guidance on Model Risk
    Management). Override for regime-specific risk appetites -- e.g.,
    BCB may require tighter thresholds for credit-risk models.
    """

    moderate: float = 0.1
    significant: float = 0.25

    def __post_init__(self) -> None:
        if not 0.0 < self.moderate < self.significant:
            raise ValueError(
                f"thresholds must satisfy 0 < moderate < significant, "
                f"got moderate={self.moderate}, significant={self.significant}"
            )


#: Default thresholds per OCC 2011-12.
OCC_DRIFT_THRESHOLDS = DriftThresholds(moderate=0.1, significant=0.25)


@dataclass(frozen=True)
class DriftSeverity:
    """PSI-based drift classification."""

    psi: float
    level: str  # "none" | "moderate" | "significant"

    @staticmethod
    def classify(
        psi: float,
        thresholds: DriftThresholds | None = None,
    ) -> DriftSeverity:
        """Classify drift severity from a PSI value.

        Parameters
        ----------
        psi:
            Population Stability Index value.
        thresholds:
            Configurable thresholds. Defaults to OCC 2011-12 values
            (moderate=0.1, significant=0.25).
        """
        t = thresholds or OCC_DRIFT_THRESHOLDS
        if psi < t.moderate:
            level = "none"
        elif psi < t.significant:
            level = "moderate"
        else:
            level = "significant"
        return DriftSeverity(psi=psi, level=level)


@dataclass(frozen=True)
class CBPEEstimate:
    """Confidence-Based Performance Estimation result.

    Estimates model accuracy from confidence scores alone (no labels),
    following the NannyML CBPE approach. In banking, ground-truth labels
    for regulatory QA are rarely available in real-time; CBPE bridges
    the gap by treating calibrated confidence as a proxy for correctness
    probability.

    ``estimated_accuracy`` is the mean of confidence scores -- valid only
    when the model is well-calibrated (low ECE). ``calibration_warning``
    flags when reference ECE is too high for CBPE to be reliable.
    """

    estimated_accuracy: float
    reference_accuracy: float
    reference_ece: float
    delta: float
    calibration_warning: bool

    @staticmethod
    def estimate(
        current_confidences: NDArray[np.floating[Any]],
        reference_accuracy: float,
        reference_ece: float,
        *,
        ece_threshold: float = 0.10,
    ) -> CBPEEstimate:
        """Estimate performance from confidence scores under drift.

        Parameters
        ----------
        current_confidences:
            Confidence scores from the current (possibly drifted) window.
        reference_accuracy:
            Accuracy observed on the reference (labeled) evaluation set.
        reference_ece:
            ECE on the reference set -- indicates how trustworthy CBPE
            estimates are. High ECE means confidence != P(correct).
        ece_threshold:
            ECE above this value triggers ``calibration_warning``.
        """
        arr = np.asarray(current_confidences, dtype=np.float64).ravel()
        if arr.size == 0:
            raise ValueError("current_confidences must be non-empty")
        estimated = float(np.mean(arr))
        return CBPEEstimate(
            estimated_accuracy=estimated,
            reference_accuracy=reference_accuracy,
            reference_ece=reference_ece,
            delta=estimated - reference_accuracy,
            calibration_warning=reference_ece > ece_threshold,
        )


@dataclass(frozen=True)
class DriftReport:
    """Combined drift analysis for one monitoring window."""

    reference_profile: DriftProfile
    current_profile: DriftProfile
    drift_severity: DriftSeverity
    cbpe: CBPEEstimate | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialize this record to a plain dictionary for JSON-friendly output."""
        result: dict[str, object] = {
            "reference": self.reference_profile.to_dict(),
            "current": self.current_profile.to_dict(),
            "psi": self.drift_severity.psi,
            "drift_level": self.drift_severity.level,
        }
        if self.cbpe is not None:
            result["cbpe"] = {
                "estimated_accuracy": self.cbpe.estimated_accuracy,
                "reference_accuracy": self.cbpe.reference_accuracy,
                "delta": self.cbpe.delta,
                "calibration_warning": self.cbpe.calibration_warning,
            }
        return result


def analyze_drift(
    reference_confidences: NDArray[np.floating[Any]],
    current_confidences: NDArray[np.floating[Any]],
    *,
    reference_accuracy: float | None = None,
    reference_ece: float | None = None,
    n_bins: int = 20,
) -> DriftReport:
    """One-call drift analysis comparing reference and current windows.

    Returns a :class:`DriftReport` with PSI-based drift severity and
    optionally a CBPE performance estimate (when ``reference_accuracy``
    and ``reference_ece`` are provided).
    """
    ref_profile = DriftProfile.from_confidences(reference_confidences, n_bins=n_bins)
    cur_profile = DriftProfile.from_confidences(current_confidences, n_bins=n_bins)
    psi = population_stability_index(ref_profile, cur_profile)
    severity = DriftSeverity.classify(psi)

    cbpe = None
    if reference_accuracy is not None and reference_ece is not None:
        cbpe = CBPEEstimate.estimate(
            current_confidences,
            reference_accuracy=reference_accuracy,
            reference_ece=reference_ece,
        )

    return DriftReport(
        reference_profile=ref_profile,
        current_profile=cur_profile,
        drift_severity=severity,
        cbpe=cbpe,
    )


__all__ = [
    "CBPEEstimate",
    "DriftProfile",
    "DriftReport",
    "DriftSeverity",
    "DriftThresholds",
    "OCC_DRIFT_THRESHOLDS",
    "analyze_drift",
    "population_stability_index",
]
