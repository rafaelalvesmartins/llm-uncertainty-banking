# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""lub.challenge.meta_calibration -- calibrate CEC's own predictions.

Every CEC report carries a calibrated confidence number on its own
claims. When the module says *"estimator X is dominant on this
domain,"* it accompanies *"P(this claim still holds in 30 days) =
0.78."*

This meta-confidence is trained on the ledger's own outcomes: every
prior CEC claim that has aged past its prediction window contributes
a ``(predicted_confidence, actual_held_up)`` pair to a calibration
curve specific to CEC outputs. Over time, CEC learns how honest it
is about itself.

This is the publishable core of CEC. *"Calibrated meta-prediction in
continuous model risk monitoring"* -- there's no published baseline.

Spec: planning/24_CEC_Spec_2026-04-25.md section 1.3 + section 4 step 3.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _stamp(moment: datetime) -> str:
    """Render *moment* in the ledger's timestamp format (UTC, trailing Z).

    The ledger writes ``strftime('%Y-%m-%dT%H:%M:%fZ', 'now')``. Careful:
    SQLite's ``%f`` means *seconds with a fractional part* (``SS.SSS``),
    whereas Python's ``%f`` means microseconds alone — hence the explicit
    ``%S`` here and the truncation from microseconds to milliseconds.
    """
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# A claim is mature once its revisit horizon has elapsed. SQLite's julianday()
# parses the schema's ISO-8601 stamps (Z suffix included) and returns days as a
# float, so the comparison is a plain subtraction.
_MATURITY_PREDICATE = "julianday(?) - julianday(p.created_at) >= p.horizon_days"


@dataclass(frozen=True)
class CalibrationCurve:
    """Reliability curve for CEC's own meta-predictions.

    Bin-aggregated; each bin has a
    ``(predicted_confidence_midpoint, observed_hold_rate, n_in_bin)``
    triple. Empty bins still appear in the list so a downstream
    plotter can render a stable x-axis.
    """

    bins: list[tuple[float, float, int]] = field(default_factory=list)
    ece: float = 0.0  # Expected Calibration Error over CEC's own claims


class MetaCalibrator:
    """Calibrate CEC's own claims against ledger-recorded outcomes.

    Predictions and outcomes are persisted to :mod:`lub.ledger` via
    the additive ``cec_meta_predictions`` and ``cec_meta_outcomes``
    tables (schema v2 migration).

    Spec: planning/24_CEC_Spec_2026-04-25.md section 1.3.
    """

    def __init__(self, ledger: Any, *, n_bins: int = 10) -> None:
        if n_bins < 2 or n_bins > 100:
            raise ValueError(f"n_bins must be in [2, 100], got {n_bins}")
        self._ledger = ledger
        self._n_bins = int(n_bins)

    def _conn(self) -> sqlite3.Connection:
        return self._ledger._conn  # type: ignore[no-any-return]  # noqa: SLF001 -- first-party extension

    # ------------------------------------------------------------------
    # Writers
    # ------------------------------------------------------------------

    def add_prediction(
        self,
        claim_id: str,
        predicted_confidence: float,
        horizon_days: int,
    ) -> None:
        """Record a CEC claim that should be revisited in ``horizon_days`` days."""
        if not 0.0 <= predicted_confidence <= 1.0:
            raise ValueError(f"predicted_confidence must be in [0, 1], got {predicted_confidence}")
        if horizon_days < 0:
            raise ValueError(f"horizon_days must be non-negative, got {horizon_days}")
        conn = self._conn()
        conn.execute(
            "INSERT OR IGNORE INTO cec_meta_predictions"
            " (claim_id, predicted_confidence, horizon_days) VALUES (?, ?, ?)",
            (str(claim_id), float(predicted_confidence), int(horizon_days)),
        )
        conn.commit()

    def record_outcome(self, claim_id: str, held_up: bool) -> None:
        """Record whether a previously-predicted claim held up."""
        conn = self._conn()
        row = conn.execute(
            "SELECT 1 FROM cec_meta_predictions WHERE claim_id = ?",
            (str(claim_id),),
        ).fetchone()
        if row is None:
            raise KeyError(
                f"no prediction recorded for claim_id={claim_id!r}; call add_prediction() first"
            )
        conn.execute(
            "INSERT OR REPLACE INTO cec_meta_outcomes (claim_id, held_up) VALUES (?, ?)",
            (str(claim_id), int(bool(held_up))),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Readers
    # ------------------------------------------------------------------

    def _paired_observations(self, *, now: datetime | None = None) -> list[tuple[float, int]]:
        """Return ``(predicted_confidence, held_up)`` pairs for matured claims.

        A claim counts only once ``horizon_days`` have elapsed since it was
        recorded. Without that filter the meta-calibration would score claims
        that have not yet had the opportunity to be wrong, which makes the
        forward-looking guarantee decorative — a 30-day claim marked "held up"
        the same afternoon would improve the curve.

        ``now`` is injectable so callers (and tests) can evaluate the curve at
        an arbitrary moment without waiting or mutating the clock.
        """
        moment = datetime.now(UTC) if now is None else now
        conn = self._conn()
        rows = conn.execute(
            "SELECT p.predicted_confidence AS conf, o.held_up AS held"
            " FROM cec_meta_predictions p"
            " JOIN cec_meta_outcomes o ON o.claim_id = p.claim_id"
            f" WHERE {_MATURITY_PREDICATE}",
            (_stamp(moment),),
        ).fetchall()
        return [(float(r["conf"]), int(r["held"])) for r in rows]

    def pending_claims(self, *, now: datetime | None = None) -> int:
        """Count claims that have an outcome but have not matured yet.

        The visible counterpart to the maturity filter: a report that shows a
        curve over *n* observations should also say how many are still ripening,
        otherwise the filter looks like missing data.
        """
        moment = datetime.now(UTC) if now is None else now
        conn = self._conn()
        row = conn.execute(
            "SELECT COUNT(*) AS n"
            " FROM cec_meta_predictions p"
            " JOIN cec_meta_outcomes o ON o.claim_id = p.claim_id"
            f" WHERE NOT ({_MATURITY_PREDICATE})",
            (_stamp(moment),),
        ).fetchone()
        return int(row["n"])

    def reliability_curve(self, *, now: datetime | None = None) -> CalibrationCurve:
        """Compute the calibration curve over matured outcome pairs."""
        observations = self._paired_observations(now=now)
        n_bins = self._n_bins
        width = 1.0 / n_bins
        buckets: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
        for conf, held in observations:
            conf = min(max(conf, 0.0), 1.0)
            idx = min(int(conf / width), n_bins - 1)
            buckets[idx].append((conf, held))

        bins: list[tuple[float, float, int]] = []
        ece_acc = 0.0
        total = sum(len(b) for b in buckets)
        for i, entries in enumerate(buckets):
            mid = (i + 0.5) * width
            if not entries:
                bins.append((mid, 0.0, 0))
                continue
            mean_conf = sum(e[0] for e in entries) / len(entries)
            hold_rate = sum(e[1] for e in entries) / len(entries)
            bins.append((mean_conf, hold_rate, len(entries)))
            if total:
                ece_acc += abs(mean_conf - hold_rate) * (len(entries) / total)

        return CalibrationCurve(bins=bins, ece=ece_acc)


__all__ = ["CalibrationCurve", "MetaCalibrator"]
