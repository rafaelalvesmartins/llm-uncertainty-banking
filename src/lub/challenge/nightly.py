# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""The nightly challenge verdict — one rule, every caller.

Two consumers ask the same question: ``lub challenge-nightly`` (a scheduled
job) and the Bridge console's governance panel (a screen an operator reads).
Two implementations of "is this deployment's calibration acceptable" would
drift apart, and the one that drifts is the one nobody reruns. So the rule
lives here.

The verdict is deliberately **tri-state**:

``PASS``
    Enough labelled evidence, and measured ECE within the context's target.
``FAIL``
    Enough labelled evidence, and the target was breached. Carries the gap.
``INCONCLUSIVE``
    Not enough labelled evidence to judge. This is *not* a pass.

The third state exists because :func:`~lub.governance.drift.check_drift`
deliberately reports a cold ledger as ``passed=True`` — the right call for a
deploy gate, which must not block a fresh service, and the wrong one for a
governance verdict, where an empty or mispointed ledger would otherwise stay
green forever and "no evidence" would read as "validated". ``check_drift``
keeps its semantics; the distinction is drawn here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from lub.challenge.meta_calibration import MetaCalibrator
from lub.governance.adr import PolicyViolation
from lub.governance.drift import enforce_drift

if TYPE_CHECKING:
    from lub.governance.contexts import BoundedContext
    from lub.ledger import Ledger

__all__ = ["ChallengeVerdict", "run_nightly_challenge"]

_LOG = structlog.get_logger("lub.challenge.nightly")

PASS = "PASS"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class ChallengeVerdict:
    """Outcome of one continuous-effective-challenge evaluation.

    Carries what was measured, not merely the label: a reviewer reads the gap
    between ``measured_ece`` and ``target_ece``, and an auditor needs to know
    how many labelled outcomes stood behind it.
    """

    status: str
    reason: str
    context_name: str
    method: str
    target_ece: float
    n_samples: int
    min_samples: int
    generated_at: datetime
    measured_ece: float | None = None
    meta_ece: float = 0.0
    meta_observations: int = 0
    pending_claims: int = 0

    @property
    def passed(self) -> bool:
        """``True`` only for PASS — INCONCLUSIVE is not a pass."""
        return self.status == PASS

    def to_dict(self) -> dict[str, Any]:
        """Serialise to JSON-safe scalars for transport (BFF, reports)."""
        return {
            "status": self.status,
            "reason": self.reason,
            "context": self.context_name,
            "method": self.method,
            "measured_ece": None if self.measured_ece is None else float(self.measured_ece),
            "target_ece": float(self.target_ece),
            "n_samples": int(self.n_samples),
            "min_samples": int(self.min_samples),
            "meta_ece": float(self.meta_ece),
            "meta_observations": int(self.meta_observations),
            "pending_claims": int(self.pending_claims),
            "generated_at": self.generated_at.isoformat(),
        }


def run_nightly_challenge(
    ledger: Ledger,
    context: BoundedContext,
    *,
    method: str = "confidence",
    min_samples: int = 10,
    n_buckets: int = 10,
    now: datetime | None = None,
) -> ChallengeVerdict:
    """Evaluate *ledger* against *context* and return a tri-state verdict.

    Runs the deployment's calibration check and the challenge layer's own
    meta-calibration over matured claims, then classifies the result. ``now``
    is injectable so the meta-calibration maturity window can be evaluated at
    an arbitrary moment.
    """
    moment = datetime.now(UTC) if now is None else now
    target = float(context.calibration_target_ece)

    measured: float | None = None
    n_samples = 0
    try:
        report = enforce_drift(
            ledger, context, method=method, n_buckets=n_buckets, min_samples=min_samples
        )
    except PolicyViolation as exc:
        status = FAIL
        reason = str(exc)
        # The report is not returned when it raises; recover the figures from
        # a non-raising pass so the verdict still carries the numbers.
        from lub.governance.drift import check_drift

        recovered = check_drift(
            ledger, context, method=method, n_buckets=n_buckets, min_samples=min_samples
        )
        measured = float(recovered.measured_ece)
        n_samples = int(recovered.n_samples)
    else:
        measured = float(report.measured_ece)
        n_samples = int(report.n_samples)
        if n_samples < min_samples:
            status = INCONCLUSIVE
            reason = (
                f"insufficient evidence: {n_samples} labelled answer(s) in the ledger, "
                f"below min_samples={min_samples}. No calibration verdict is possible. "
                f"Seed the ledger (is the path right?) or lower min_samples deliberately."
            )
            measured = None
        else:
            status = PASS
            reason = (
                f"measured ECE {measured:.4f} within target {target:.4f} "
                f"over {n_samples} labelled answers"
            )

    meta = MetaCalibrator(ledger=ledger)
    curve = meta.reliability_curve(now=moment)
    pending = meta.pending_claims(now=moment)
    observations = sum(n for _, _, n in curve.bins)

    _LOG.info(
        "challenge.nightly.verdict",
        status=status,
        context=context.name,
        n_samples=n_samples,
        pending_claims=pending,
    )
    return ChallengeVerdict(
        status=status,
        reason=reason,
        context_name=context.name,
        method=method,
        target_ece=target,
        n_samples=n_samples,
        min_samples=min_samples,
        generated_at=moment,
        measured_ece=measured,
        meta_ece=curve.ece,
        meta_observations=observations,
        pending_claims=pending,
    )
