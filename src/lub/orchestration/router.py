# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Uncertainty-gated cascaded router.

Routes a prompt through an ordered list of tiers, each backed by a
pipeline, a confidence threshold, and a cost. The first tier whose
confidence meets its threshold wins. If no tier clears, the highest-
confidence tier is returned with an ABSTAIN flag.

This is the calibration-aware version of Ruflo's cost-aware model
router: dispatch is driven by *calibrated uncertainty*, not just price.

Typical use::

    from lub import UncertaintyPipeline
    from lub.orchestration import TieredRouter, Tier

    cheap = UncertaintyPipeline.from_pretrained(
        model="dummy-cheap", backend="dummy", estimator="token_logprob"
    )
    strong = UncertaintyPipeline.from_pretrained(
        model="dummy-strong", backend="dummy", estimator="p_true"
    )
    router = TieredRouter(tiers=[
        Tier(name="haiku",  pipeline=cheap,  threshold=0.80, cost=0.001),
        Tier(name="sonnet", pipeline=strong, threshold=0.70, cost=0.015),
    ])
    routed = router.answer("What is the Basel III CET1 minimum?")
    print(routed.final.answer, routed.tier_used, routed.total_cost)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from lub.types import UncertaintyResult

if TYPE_CHECKING:
    from lub.protocols import PipelineProto

_LOG = structlog.get_logger("lub.orchestration.router")

ABSTAIN_TIER = "abstain"


@dataclass(frozen=True)
class Tier:
    """One step in a cascaded router.

    Parameters
    ----------
    name:
        Human-readable identifier used in logs and audit records.
    pipeline:
        Any object with ``answer(prompt, **kwargs) -> UncertaintyResult``.
    threshold:
        Confidence cutoff in ``[0, 1]``. A result with
        ``confidence >= threshold`` wins the tier and short-circuits
        the cascade.
    cost:
        Per-call monetary cost, used only for accounting. Units are
        opaque to the router (USD, BRL, tokens — pick one).
    """

    name: str
    pipeline: PipelineProto
    threshold: float
    cost: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError(
                f"Tier {self.name!r}: threshold must be in [0, 1], got {self.threshold}"
            )
        if self.cost < 0.0:
            raise ValueError(f"Tier {self.name!r}: cost must be >= 0, got {self.cost}")


@dataclass(frozen=True)
class RouterResult:
    """Outcome of a :class:`TieredRouter` call.

    Attributes
    ----------
    final:
        The :class:`UncertaintyResult` returned to the caller. May come
        from the winning tier or, if no tier cleared, from the
        best-confidence tier (with ``should_refuse=True``).
    tier_used:
        Name of the tier whose answer was returned, or ``"abstain"``
        if no tier met its threshold.
    total_cost:
        Sum of the ``cost`` attribute of every tier invoked. Tiers that
        never run (short-circuited) do not contribute.
    escalation_path:
        One dict per tier invoked, with keys ``name``, ``confidence``,
        ``threshold``, ``passed``. Useful for audit and for plotting
        Pareto fronts.
    """

    final: UncertaintyResult
    tier_used: str
    total_cost: float
    escalation_path: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-ready dict for the ledger or audit log."""
        return {
            "final": {
                "answer": self.final.answer,
                "confidence": float(self.final.confidence),
                "should_refuse": bool(self.final.should_refuse),
                "raw_scores": dict(self.final.raw_scores),
            },
            "tier_used": self.tier_used,
            "total_cost": float(self.total_cost),
            "escalation_path": list(self.escalation_path),
        }


class TieredRouter:
    """Cascaded router with per-tier uncertainty thresholds.

    The router is stateless: each :meth:`answer` call walks the tiers
    from cheapest to strongest. If you need memory of past routing
    decisions, pair the router with :class:`lub.ledger.Ledger`.

    Parameters
    ----------
    tiers:
        Ordered list of :class:`Tier`. Order = dispatch order. Usually
        goes cheap → expensive, but the router makes no assumption.
    abstain_marker:
        String placed in :attr:`UncertaintyResult.answer` when no tier
        clears its threshold. Defaults to the same marker used by
        :class:`~lub.guard.UncertaintyGuard`.
    """

    DEFAULT_ABSTAIN_MARKER = "[ABSTAIN: no tier met confidence threshold]"

    def __init__(
        self,
        tiers: list[Tier],
        abstain_marker: str = DEFAULT_ABSTAIN_MARKER,
    ) -> None:
        if not tiers:
            raise ValueError("TieredRouter requires at least one tier")
        names = [t.name for t in tiers]
        if len(set(names)) != len(names):
            raise ValueError(f"Tier names must be unique; got {names}")
        self.tiers = list(tiers)
        self.abstain_marker = abstain_marker

    def answer(self, prompt: str, **kwargs: Any) -> RouterResult:
        """Dispatch *prompt* through the cascade and return the result."""
        total_cost = 0.0
        escalation_path: list[dict[str, Any]] = []
        best: tuple[UncertaintyResult, Tier] | None = None

        for tier in self.tiers:
            _LOG.debug("router.tier.start", tier=tier.name, threshold=tier.threshold)
            result = tier.pipeline.answer(prompt, **kwargs)
            total_cost += tier.cost
            passed = result.confidence >= tier.threshold
            escalation_path.append(
                {
                    "name": tier.name,
                    "confidence": float(result.confidence),
                    "threshold": float(tier.threshold),
                    "passed": bool(passed),
                }
            )
            if best is None or result.confidence > best[0].confidence:
                best = (result, tier)
            if passed:
                _LOG.info(
                    "router.tier.passed",
                    tier=tier.name,
                    confidence=f"{result.confidence:.4f}",
                    cost=total_cost,
                )
                return RouterResult(
                    final=result,
                    tier_used=tier.name,
                    total_cost=total_cost,
                    escalation_path=escalation_path,
                )

        # No tier cleared. Return the best-confidence answer with an abstain flag.
        assert best is not None  # noqa: S101 — tiers guaranteed non-empty above.
        best_result, best_tier = best
        abstained = best_result.with_should_refuse(True).with_answer(self.abstain_marker)
        _LOG.warning(
            "router.abstain",
            best_tier=best_tier.name,
            best_confidence=f"{best_result.confidence:.4f}",
            total_cost=total_cost,
        )
        return RouterResult(
            final=abstained,
            tier_used=ABSTAIN_TIER,
            total_cost=total_cost,
            escalation_path=escalation_path,
        )

    def batch(self, prompts: list[str], **kwargs: Any) -> list[RouterResult]:
        """Route a list of prompts. Exceptions propagate per-prompt."""
        return [self.answer(p, **kwargs) for p in prompts]


# --- Failover layer (v0.1.x ship; spec planning/25_Ruflo_Patterns_Audit_2026-04-25.md s3.1) ---
# Pattern adopted with attribution from ruvnet/ruflo (MIT) -- multi-LLM
# provider failover with automatic recovery on backend errors. LUB twist:
# calibration context is preserved by requiring secondary chains to use
# thresholds at least as strict as the primary, so a failover cannot silently
# relax the safety guarantee.


class FailoverExhausted(RuntimeError):
    """Raised when every router in a FailoverChain has errored on the same prompt.

    Carries the per-router exception list as ``causes`` so audit logs can
    record exactly which provider failed with which error.
    """

    def __init__(self, causes: list[BaseException]) -> None:
        self.causes = list(causes)
        names = ", ".join(type(c).__name__ for c in causes) or "(no causes captured)"
        super().__init__(f"FailoverChain exhausted across {len(causes)} router(s); errors: {names}")


# Exception types that count as "backend transient error" and trigger
# failover. Anything not transient (ValueError, TypeError, etc.) propagates
# so calibration bugs do not silently cascade through the chain.
_TRANSIENT_BACKEND_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    ConnectionError,
    OSError,  # covers httpx.TransportError, requests.ConnectionError, etc.
)

# Heuristic match on exception class name -- covers SDK-specific errors
# that do not inherit from the stdlib base classes above.
_TRANSIENT_BACKEND_NAME_MARKERS: tuple[str, ...] = (
    "RateLimit",
    "RateLimited",
    "Timeout",
    "ServiceUnavailable",
    "InternalServerError",
    "APIStatusError",
    "APIConnectionError",
    "TransportError",
    "TooManyRequests",
)


def _is_transient_backend_error(exc: BaseException) -> bool:
    """Return True if ``exc`` is the kind of transient error a failover should swallow."""
    if isinstance(exc, _TRANSIENT_BACKEND_EXCEPTIONS):
        return True
    name = type(exc).__name__
    return any(marker in name for marker in _TRANSIENT_BACKEND_NAME_MARKERS)


class FailoverChain:
    """Chain of TieredRouter instances with automatic failover on backend errors.

    Pattern adapted with attribution from ``ruvnet/ruflo`` (MIT). LUB twist:
    secondary routers must use abstention thresholds at least as strict as
    the primary's, so a failover never silently relaxes the safety guarantee.
    Programmer errors (ValueError, TypeError) and calibration-layer
    exceptions are NOT swallowed and propagate; only transient backend
    errors trigger failover.

    Spec: ``planning/25_Ruflo_Patterns_Audit_2026-04-25.md`` section 3.1.
    """

    def __init__(
        self,
        routers: list[TieredRouter],
        *,
        enforce_calibration_monotonicity: bool = True,
    ) -> None:
        if not routers:
            raise ValueError("FailoverChain requires at least one router.")
        if enforce_calibration_monotonicity and len(routers) > 1:
            primary_min = min(t.threshold for t in routers[0].tiers)
            for i, r in enumerate(routers[1:], start=1):
                secondary_min = min(t.threshold for t in r.tiers)
                if secondary_min < primary_min:
                    raise ValueError(
                        f"FailoverChain calibration-monotonicity violated: "
                        f"router[{i}] has min threshold {secondary_min} < primary's "
                        f"{primary_min}. Pass enforce_calibration_monotonicity=False "
                        f"to bypass (NOT recommended for SR 11-7 deployments)."
                    )
        self._routers = list(routers)

    @property
    def routers(self) -> list[TieredRouter]:
        """Read-only view of the configured chain (in dispatch order)."""
        return list(self._routers)

    def answer(self, prompt: str, **kwargs: Any) -> RouterResult:
        """Dispatch ``prompt`` through the chain; fall through on transient errors.

        Iterates ``self._routers`` in order. If a router raises a transient
        backend error (timeout, rate-limit, 5xx), logs the failover and
        continues to the next router. Non-transient exceptions propagate.

        Raises:
            FailoverExhausted: If every router in the chain errored. Carries
                the per-router cause list on ``.causes``.
        """
        causes: list[BaseException] = []
        for i, router in enumerate(self._routers):
            try:
                _LOG.debug("failover.try", router_index=i, n_routers=len(self._routers))
                result = router.answer(prompt, **kwargs)
            except Exception as exc:  # noqa: BLE001 -- re-raise non-transient below
                if not _is_transient_backend_error(exc):
                    raise
                causes.append(exc)
                _LOG.warning(
                    "failover.transient",
                    router_index=i,
                    error_type=type(exc).__name__,
                    error=str(exc)[:200],
                )
                continue
            else:
                if i > 0:
                    _LOG.info(
                        "failover.recovered",
                        router_index=i,
                        n_failed=len(causes),
                        tier_used=result.tier_used,
                    )
                return result
        raise FailoverExhausted(causes)

    def batch(self, prompts: list[str], **kwargs: Any) -> list[RouterResult]:
        """Per-prompt failover. Each prompt independently walks the chain."""
        return [self.answer(p, **kwargs) for p in prompts]


__all__ = [
    "ABSTAIN_TIER",
    "FailoverChain",
    "FailoverExhausted",
    "RouterResult",
    "Tier",
    "TieredRouter",
]
