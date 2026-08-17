# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Ledger-driven drift enforcement.

The bounded-context ADRs declare a ``calibration_target_ece``. In
production, the measured ECE must stay at or below that target —
otherwise the governance runtime must escalate (abstain, revalidate,
or alert).

This module computes ECE from ledger replay output and raises
:class:`~lub.governance.adr.PolicyViolation` when the target is
breached. It is stdlib-only and has no heavy dependencies, so nightly
calibration CI can run it on the exact same SQLite ledger the
production workload writes to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from lub.governance.adr import PolicyViolation

if TYPE_CHECKING:
    from lub.governance.contexts import BoundedContext
    from lub.ledger.store import CalibrationPoint, Ledger

_LOG = structlog.get_logger("lub.governance.drift")


@dataclass(frozen=True)
class DriftReport:
    """Outcome of a drift check against a bounded context.

    Attributes
    ----------
    context_name:
        The :class:`~lub.governance.contexts.BoundedContext` name under
        test.
    method:
        The UQ method whose reliability the report summarises.
    measured_ece:
        Weighted mean absolute gap between confidence and accuracy
        across the reliability buckets (the classic ECE).
    target_ece:
        The context's ``calibration_target_ece``.
    passed:
        ``True`` iff ``measured_ece <= target_ece`` and enough samples
        contributed to be meaningful.
    n_samples:
        Total number of labelled answers used for the computation.
    """

    context_name: str
    method: str
    measured_ece: float
    target_ece: float
    passed: bool
    n_samples: int

    def __str__(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        return (
            f"DriftReport[{verdict}] {self.context_name}::{self.method} "
            f"ece={self.measured_ece:.4f} target={self.target_ece:.4f} "
            f"n={self.n_samples}"
        )


def compute_ece(points: list[CalibrationPoint]) -> float:
    """Expected Calibration Error from reliability-diagram buckets.

    ECE = Σ_b (n_b / N) * |conf_mean_b − accuracy_b|, where the sum is
    taken over populated buckets only.

    Returns ``0.0`` when no bucket contributed any samples (the ledger
    is empty); callers should cross-check ``n_samples`` before
    interpreting this as "calibrated".
    """
    total = sum(p.n for p in points)
    if total == 0:
        return 0.0
    return sum((p.n / total) * abs(p.confidence_mean - p.accuracy) for p in points)


def check_drift(
    ledger: Ledger,
    context: BoundedContext,
    *,
    method: str = "confidence",
    n_buckets: int = 10,
    min_samples: int = 10,
) -> DriftReport:
    """Compute a :class:`DriftReport` without raising.

    Parameters
    ----------
    ledger:
        Open :class:`~lub.ledger.store.Ledger` (context-manager entered).
    context:
        The bounded context whose ``calibration_target_ece`` is the
        threshold.
    method:
        UQ method to replay (must match what was logged to
        ``uq_scores.method``).
    n_buckets:
        Number of equal-width buckets for the reliability diagram.
    min_samples:
        A measurement with fewer than this many labelled outcomes is
        reported as *inconclusive* (``passed=True``) — we do not
        want to fail a deploy because the ledger is cold.
    """
    points = ledger.replay_calibration(method=method, n_buckets=n_buckets)
    n_samples = sum(p.n for p in points)
    measured = compute_ece(points)

    if n_samples < min_samples:
        _LOG.info(
            "drift.inconclusive",
            context=context.name,
            method=method,
            n=n_samples,
            min_samples=min_samples,
        )
        return DriftReport(
            context_name=context.name,
            method=method,
            measured_ece=measured,
            target_ece=context.calibration_target_ece,
            passed=True,
            n_samples=n_samples,
        )

    passed = measured <= context.calibration_target_ece
    _LOG.info(
        "drift.checked",
        context=context.name,
        method=method,
        measured=f"{measured:.4f}",
        target=f"{context.calibration_target_ece:.4f}",
        passed=passed,
        n=n_samples,
    )
    return DriftReport(
        context_name=context.name,
        method=method,
        measured_ece=measured,
        target_ece=context.calibration_target_ece,
        passed=passed,
        n_samples=n_samples,
    )


def enforce_drift(
    ledger: Ledger,
    context: BoundedContext,
    *,
    method: str = "confidence",
    n_buckets: int = 10,
    min_samples: int = 10,
) -> DriftReport:
    """Compute drift and raise :class:`PolicyViolation` on failure.

    Use this in nightly CI so a calibration regression fails the build.
    Callers who want to merely log should use :func:`check_drift`.
    """
    report = check_drift(
        ledger,
        context,
        method=method,
        n_buckets=n_buckets,
        min_samples=min_samples,
    )
    if not report.passed:
        raise PolicyViolation(
            f"calibration drift in context {context.name!r} (method={method}): "
            f"measured ECE {report.measured_ece:.4f} > target "
            f"{report.target_ece:.4f} over {report.n_samples} samples"
        )
    return report


__all__ = [
    "DriftReport",
    "check_drift",
    "compute_ece",
    "enforce_drift",
]
