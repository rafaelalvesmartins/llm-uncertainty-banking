# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Complexity-aware wrapper around :class:`~lub.orchestration.TieredRouter`.

Bridge ships two cost-control collaborators that *should* talk to each
other but, until this module, do not:

* :class:`~lub.connectors.bridge.complexity.ComplexityRouter` --
  heuristically scores each query as
  :class:`~lub.connectors.bridge.complexity.ComplexityTier.SIMPLE`,
  ``MEDIUM``, or ``COMPLEX``.
* :class:`~lub.orchestration.TieredRouter` -- walks an ordered
  cheap-to-expensive cascade and short-circuits on the first tier whose
  calibrated confidence clears its threshold.

A grep for ``ComplexityRouter`` finds no callers outside its own module,
so the 5-10x cost saving advertised in
:mod:`lub.connectors.bridge.complexity` is currently aspirational: the
heuristic scorer produces an audit-grade tier label that nothing reads.
At the same time, :class:`BridgePlatform`'s router-fallback path always
starts the cascade at tier 0, so a balance-check ("qual meu saldo?")
burns the cheap-tier call and *then* the mid-tier and *then* the
frontier on its way to abstain, while a regulatory question pays the
warm-up cost on tiers it cannot satisfy.

:class:`ComplexityRoutedAnswer` closes that gap. It composes a
:class:`ComplexityRouter` with a :class:`TieredRouter` and *trims* the
cascade per query:

* ``SIMPLE``  -> only the cheapest tier(s) ever run; the cascade
  refuses to escalate to the frontier model on a balance-check.
* ``MEDIUM``  -> skip the cheap tier; start at the mid-tier and
  continue upward.
* ``COMPLEX`` -> jump straight to the strongest tier and skip the
  cheap warm-ups entirely (a regulatory question never burns the
  cheap call to "warm up" -- it costs latency without helping
  accuracy).

The trim is conservative: it caps which tiers are eligible but never
overrides the calibrated abstention decision. If the trimmed slice
fails to clear its thresholds, the result still abstains -- it will
not silently expand back to the cheap tier and pretend it answered.
That preserves the SR 11-7 / BCB 4893 invariant that no cost
optimization can mask a low-confidence outcome.

Banking notes
-------------

* Every routed call records the complexity tier, the chosen slice
  (``slice_start``, ``slice_end``), the trimmed tier names, and the
  scorer's rationale at the head of
  :attr:`~lub.orchestration.RouterResult.escalation_path` so a regulator
  asking "why did this query hit only the cheap model?" gets a
  structured answer.
* Tier-up is preferred over tier-down on ambiguity -- mis-routing a
  ``COMPLEX`` query as ``MEDIUM`` costs goodwill; mis-routing a
  ``SIMPLE`` query as ``COMPLEX`` only costs money. This mirrors the
  conservative bias documented in
  :mod:`~lub.connectors.bridge.complexity`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from lub.connectors.bridge.complexity import (
    ComplexityRouter,
    ComplexityScore,
    ComplexityTier,
)
from lub.orchestration import RouterResult, Tier, TieredRouter

__all__ = [
    "ComplexityRoutedAnswer",
    "TierBudget",
]

_LOG = structlog.get_logger("lub.bridge.complexity_routed")


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TierBudget:
    """Per-complexity-tier eligibility caps over the underlying cascade.

    All indices are *inclusive* and refer to positions in
    :attr:`TieredRouter.tiers`. Negative indices wrap from the end (so
    ``-1`` always means "the strongest tier" regardless of cascade
    depth, which keeps the default budget meaningful when a deployment
    later adds a fourth tier).

    Attributes
    ----------
    simple_start, simple_end:
        Index range eligible for
        :attr:`~lub.connectors.bridge.complexity.ComplexityTier.SIMPLE`.
        Defaults to ``(0, 0)`` -- only the cheapest tier runs.
    medium_start, medium_end:
        Range for
        :attr:`~lub.connectors.bridge.complexity.ComplexityTier.MEDIUM`.
        Defaults to ``(1, -1)`` -- skip tier 0, then continue upward
        through the cascade. When the cascade has only one tier this
        collapses gracefully to that single tier (see :meth:`resolve`).
    complex_start, complex_end:
        Range for
        :attr:`~lub.connectors.bridge.complexity.ComplexityTier.COMPLEX`.
        Defaults to ``(-1, -1)`` -- jump straight to the strongest tier
        and run only that.
    """

    simple_start: int = 0
    simple_end: int = 0
    medium_start: int = 1
    medium_end: int = -1
    complex_start: int = -1
    complex_end: int = -1

    def resolve(self, tier: ComplexityTier, total: int) -> tuple[int, int]:
        """Return inclusive ``(start, end)`` clamped to ``[0, total - 1]``.

        Resolves negative indices, swaps inverted ranges, and clamps
        out-of-range values so any reasonable budget produces a usable
        slice even when the underlying cascade has fewer tiers than the
        budget assumed -- the typical bootstrapping case where only a
        single cheap tier is configured during early deployment.
        """
        if total < 1:
            raise ValueError("cannot resolve budget against an empty cascade")

        if tier is ComplexityTier.SIMPLE:
            raw_start, raw_end = self.simple_start, self.simple_end
        elif tier is ComplexityTier.MEDIUM:
            raw_start, raw_end = self.medium_start, self.medium_end
        else:
            raw_start, raw_end = self.complex_start, self.complex_end

        start = raw_start + total if raw_start < 0 else raw_start
        end = raw_end + total if raw_end < 0 else raw_end
        start = max(0, min(start, total - 1))
        end = max(0, min(end, total - 1))
        if start > end:
            start, end = end, start
        return start, end


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@dataclass
class ComplexityRoutedAnswer:
    """Wrap a :class:`TieredRouter` with complexity-driven tier trimming.

    Parameters
    ----------
    router:
        The :class:`TieredRouter` whose cascade should be trimmed per
        query. Must hold at least one tier.
    complexity:
        Configured :class:`ComplexityRouter`. Defaults to a fresh
        instance with the module-level thresholds calibrated for
        Brazilian banking traffic.
    budget:
        :class:`TierBudget` selecting the eligible slice per
        complexity tier. Defaults map ``SIMPLE`` to tier 0 only,
        ``MEDIUM`` to tiers ``1..-1``, and ``COMPLEX`` to the strongest
        tier only.

    Notes
    -----
    The wrapper does not mutate ``router``. Each :meth:`answer` call
    constructs a *transient* :class:`TieredRouter` over the eligible
    slice, so the configured cascade stays intact for callers that
    bypass complexity routing (debug surfaces, replays, baseline
    benchmarks).

    Calibration is preserved by reusing the underlying tiers directly
    -- they keep their thresholds and pipelines, so the abstention
    decision the trimmed cascade reports is the same one the full
    cascade would have reported on that same slice. The wrapper
    cannot make a low-confidence call look confident; it can only
    refuse to spend budget on tiers that have no business answering.
    """

    router: TieredRouter
    complexity: ComplexityRouter = field(default_factory=ComplexityRouter)
    budget: TierBudget = field(default_factory=TierBudget)

    def __post_init__(self) -> None:
        if not isinstance(self.router, TieredRouter):
            raise TypeError(f"router must be a TieredRouter, got {type(self.router).__name__}")
        if not isinstance(self.complexity, ComplexityRouter):
            raise TypeError(
                f"complexity must be a ComplexityRouter, got {type(self.complexity).__name__}"
            )
        if not isinstance(self.budget, TierBudget):
            raise TypeError(f"budget must be a TierBudget, got {type(self.budget).__name__}")
        if not self.router.tiers:
            raise ValueError("router has no tiers; nothing to trim")

    def answer(self, prompt: str, **kwargs: Any) -> RouterResult:
        """Score complexity, trim the cascade, dispatch via :class:`TieredRouter`.

        The returned :attr:`RouterResult.escalation_path` is prepended
        with a complexity-marker entry so audit consumers see the
        complexity decision alongside the per-tier confidence trace
        produced by the underlying router.
        """
        score = self.complexity.score(prompt)
        start, end = self.budget.resolve(score.tier, len(self.router.tiers))
        trimmed: list[Tier] = list(self.router.tiers[start : end + 1])

        _LOG.info(
            "bridge.complexity_routed.dispatch",
            complexity_tier=score.tier.value,
            raw_score=score.raw_score,
            slice_start=start,
            slice_end=end,
            tier_names=[t.name for t in trimmed],
        )

        scoped = TieredRouter(
            tiers=trimmed,
            abstain_marker=self.router.abstain_marker,
        )
        result = scoped.answer(prompt, **kwargs)

        complexity_event = self._complexity_audit_event(score, start, end, trimmed)
        return RouterResult(
            final=result.final,
            tier_used=result.tier_used,
            total_cost=result.total_cost,
            escalation_path=[complexity_event, *result.escalation_path],
        )

    @staticmethod
    def _complexity_audit_event(
        score: ComplexityScore,
        start: int,
        end: int,
        trimmed: list[Tier],
    ) -> dict[str, Any]:
        """Build the marker entry prepended to the audit trail.

        The entry uses ``name="complexity"`` as a sentinel so audit
        consumers iterating :attr:`RouterResult.escalation_path` can
        distinguish the complexity decision from per-tier verdicts. The
        ``rationale`` field carries the human-readable signal summary
        from :class:`~lub.connectors.bridge.complexity.ComplexityRouter`
        for BCB 4893 reviewers.
        """
        return {
            "name": "complexity",
            "complexity_tier": score.tier.value,
            "raw_score": float(score.raw_score),
            "rationale": score.rationale,
            "slice_start": start,
            "slice_end": end,
            "trimmed_tier_names": [t.name for t in trimmed],
        }
