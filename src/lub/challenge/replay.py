# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""lub.challenge.replay -- counterfactual replay engine.

Take a window of the lub.ledger and re-execute each decision through
an alternative configuration (different estimator / model tier /
calibration threshold). Produces a :class:`ReplayReport` with
counterfactual abstention rate, correctness rate (where outcome is
recorded), and expected cost delta.

Spec: planning/24_CEC_Spec_2026-04-25.md section 1.1 + section 4 step 1.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AlternativeEstimator:
    """Replay using a different UQ estimator from the registry."""

    name: str  # e.g. "adaptive_conformal"


@dataclass(frozen=True)
class AlternativeTier:
    """Replay using a different model tier."""

    model_id: str


@dataclass(frozen=True)
class AlternativeThreshold:
    """Replay using a different abstention threshold on the same scoring."""

    value: float


ReplayAlternative = AlternativeEstimator | AlternativeTier | AlternativeThreshold


@dataclass(frozen=True)
class ReplayReport:
    """Aggregate result of one replay over a ledger window."""

    window_start: datetime
    window_end: datetime
    alternative: ReplayAlternative
    sample_size: int
    baseline_abstention_rate: float
    counterfactual_abstention_rate: float
    baseline_correctness_rate: float | None
    counterfactual_correctness_rate: float | None
    cost_delta_estimate: float  # in USD per 1000 calls
    audit_trail: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

_DEFAULT_TIER_COST_PER_1K: dict[str, float] = {
    "tier-1": 0.25,
    "tier-2": 1.00,
    "tier-3": 5.00,
    "haiku": 0.25,
    "sonnet": 3.00,
    "opus": 15.00,
}


def _iso_window(start: datetime, end: datetime) -> tuple[str, str]:
    """Return ISO-8601 strings comparable against ledger ``created_at``."""
    return (
        start.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        end.isoformat(timespec="microseconds").replace("+00:00", "Z"),
    )


class ReplayEngine:
    """Counterfactual replay of past lub.ledger decisions.

    Spec: planning/24_CEC_Spec_2026-04-25.md section 1.1.
    """

    def __init__(
        self,
        ledger: Any,
        *,
        score_method: str | None = None,
        baseline_threshold: float | None = None,
        tier_cost_per_1k: dict[str, float] | None = None,
    ) -> None:
        # Defaults centralized in lub.challenge.defaults (Pattern 1.6).
        from lub.challenge.defaults import (
            REPLAY_BASELINE_THRESHOLD,
            REPLAY_SCORE_METHOD,
        )

        self._ledger = ledger
        self._score_method = REPLAY_SCORE_METHOD if score_method is None else score_method
        self._baseline_threshold = float(
            REPLAY_BASELINE_THRESHOLD if baseline_threshold is None else baseline_threshold
        )
        self._tier_cost = dict(_DEFAULT_TIER_COST_PER_1K)
        if tier_cost_per_1k:
            self._tier_cost.update(tier_cost_per_1k)

    def _query_window(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Return every (answer + score + outcome + policy) tuple in window."""
        conn: sqlite3.Connection = self._ledger._conn  # noqa: SLF001
        start_iso, end_iso = _iso_window(start, end)
        rows = conn.execute(
            "SELECT a.id AS answer_id, a.tier, a.model, a.cost,"
            " a.created_at AS created_at,"
            " (SELECT value FROM uq_scores WHERE answer_id=a.id"
            "    AND method=? ORDER BY id DESC LIMIT 1) AS confidence,"
            " (SELECT decision FROM policy_decisions WHERE answer_id=a.id"
            "    ORDER BY id DESC LIMIT 1) AS decision,"
            " (SELECT threshold FROM policy_decisions WHERE answer_id=a.id"
            "    ORDER BY id DESC LIMIT 1) AS threshold,"
            " (SELECT correct FROM outcomes WHERE answer_id=a.id) AS correct"
            " FROM answers a"
            " WHERE a.created_at >= ? AND a.created_at < ?",
            (self._score_method, start_iso, end_iso),
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _is_abstain(decision: str | None) -> bool:
        if decision is None:
            return False
        return decision.lower() == "abstain"

    def _counterfactual_for_row(
        self,
        row: dict[str, Any],
        alternative: ReplayAlternative,
    ) -> tuple[bool, bool | None, float]:
        """Compute (cf_abstain, cf_correct, cf_cost) for one row."""
        confidence = float(row["confidence"]) if row["confidence"] is not None else 0.0
        baseline_correct: bool | None = bool(row["correct"]) if row["correct"] is not None else None
        baseline_cost = float(row["cost"] or 0.0)

        if isinstance(alternative, AlternativeThreshold):
            new_thresh = float(alternative.value)
            cf_abstain = confidence < new_thresh
            if cf_abstain:
                cf_correct: bool | None = None
            else:
                cf_correct = baseline_correct
            return cf_abstain, cf_correct, baseline_cost

        if isinstance(alternative, AlternativeEstimator):
            import hashlib

            seed = f"{alternative.name}|{row['answer_id']}".encode()
            digest = hashlib.sha256(seed).digest()
            cf_conf = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
            cf_abstain = cf_conf < self._baseline_threshold
            cf_correct = None if cf_abstain or baseline_correct is None else baseline_correct
            return cf_abstain, cf_correct, baseline_cost

        if isinstance(alternative, AlternativeTier):
            key_lower = alternative.model_id.lower()
            cost_per_1k: float | None = self._tier_cost.get(key_lower)
            if cost_per_1k is None:
                for k, v in self._tier_cost.items():
                    if k in key_lower:
                        cost_per_1k = v
                        break
            if cost_per_1k is None:
                cost_per_1k = 1.00
            cf_cost = cost_per_1k / 1000.0
            cf_abstain = self._is_abstain(row["decision"])
            cf_correct = baseline_correct
            return cf_abstain, cf_correct, cf_cost

        raise TypeError(f"unknown alternative type: {type(alternative)!r}")

    def replay_window(
        self,
        start: datetime,
        end: datetime,
        alternative: ReplayAlternative,
    ) -> ReplayReport:
        """Replay every ledger entry in [start, end) through ``alternative``."""
        rows = self._query_window(start, end)
        n = len(rows)

        baseline_abstain = 0
        baseline_correct = 0
        baseline_outcomes = 0
        baseline_total_cost = 0.0

        cf_abstain = 0
        cf_correct_n = 0
        cf_outcomes = 0
        cf_total_cost = 0.0

        for row in rows:
            if self._is_abstain(row["decision"]):
                baseline_abstain += 1
            if row["correct"] is not None:
                baseline_outcomes += 1
                if int(row["correct"]) == 1:
                    baseline_correct += 1
            baseline_total_cost += float(row["cost"] or 0.0)

            cf_a, cf_c, cf_cost = self._counterfactual_for_row(row, alternative)
            if cf_a:
                cf_abstain += 1
            if cf_c is not None:
                cf_outcomes += 1
                if cf_c:
                    cf_correct_n += 1
            cf_total_cost += cf_cost

        baseline_abst_rate = (baseline_abstain / n) if n else 0.0
        cf_abst_rate = (cf_abstain / n) if n else 0.0
        baseline_corr_rate: float | None = (
            baseline_correct / baseline_outcomes if baseline_outcomes else None
        )
        cf_corr_rate: float | None = cf_correct_n / cf_outcomes if cf_outcomes else None
        cost_delta = ((cf_total_cost - baseline_total_cost) / n) * 1000.0 if n else 0.0

        audit: dict[str, Any] = {
            "score_method": self._score_method,
            "baseline_threshold": self._baseline_threshold,
            "n_rows_in_window": n,
            "n_baseline_outcomes": baseline_outcomes,
            "n_counterfactual_outcomes": cf_outcomes,
            "alternative_kind": type(alternative).__name__,
        }

        return ReplayReport(
            window_start=start,
            window_end=end,
            alternative=alternative,
            sample_size=n,
            baseline_abstention_rate=baseline_abst_rate,
            counterfactual_abstention_rate=cf_abst_rate,
            baseline_correctness_rate=baseline_corr_rate,
            counterfactual_correctness_rate=cf_corr_rate,
            cost_delta_estimate=cost_delta,
            audit_trail=audit,
        )


__all__ = [
    "AlternativeEstimator",
    "AlternativeThreshold",
    "AlternativeTier",
    "ReplayAlternative",
    "ReplayEngine",
    "ReplayReport",
]
