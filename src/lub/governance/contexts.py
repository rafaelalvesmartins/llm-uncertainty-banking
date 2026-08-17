# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""DDD-style bounded contexts for calibration policy."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BoundedContext(BaseModel):
    """One calibration policy surface.

    A bounded context is the unit of calibration scope. Different
    domains have different risk appetites — regulatory QA cannot
    tolerate hallucinations, while fraud alerts are fine with more
    false positives. One :class:`BoundedContext` per domain.

    Attributes
    ----------
    name:
        Stable identifier. Used as a key in :class:`ContextRegistry`
        and written to ``queries.domain`` in the ledger.
    domain:
        Short human description, e.g. ``"retail-credit"``.
    calibration_target_ece:
        Maximum acceptable Expected Calibration Error. Defaults to
        ``0.05`` (5 percent).
    coverage_target:
        Fraction of queries the runtime is expected to answer without
        abstaining, conditional on ``risk_ceiling``. Defaults to
        ``0.80``.
    risk_ceiling:
        Maximum acceptable error rate on answered queries. Defaults
        to ``0.02`` (2 percent).
    tier_order:
        Ordered list of tier names that the :class:`TieredRouter`
        should dispatch through for this context.
    abstain_marker:
        Override for the default abstain string, if regulatory policy
        demands a specific wording.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    calibration_target_ece: float = Field(default=0.05, ge=0.0, le=1.0)
    coverage_target: float = Field(default=0.80, ge=0.0, le=1.0)
    risk_ceiling: float = Field(default=0.02, ge=0.0, le=1.0)
    tier_order: list[str] = Field(default_factory=list)
    abstain_marker: str = "[ABSTAIN]"


class ContextRegistry:
    """In-memory lookup keyed by :attr:`BoundedContext.name`."""

    def __init__(self) -> None:
        self._by_name: dict[str, BoundedContext] = {}

    def register(self, ctx: BoundedContext) -> None:
        """Register a bounded context, raising if its name is already taken."""
        if ctx.name in self._by_name:
            raise ValueError(f"BoundedContext {ctx.name!r} already registered")
        self._by_name[ctx.name] = ctx

    def get(self, name: str) -> BoundedContext:
        """Return the registered context for ``name`` or raise ``KeyError``."""
        if name not in self._by_name:
            raise KeyError(f"No BoundedContext registered for {name!r}")
        return self._by_name[name]

    def all(self) -> dict[str, BoundedContext]:
        """Return a shallow copy of the name-to-context mapping."""
        return dict(self._by_name)

    def to_dict(self) -> dict[str, Any]:
        """Serialize all registered contexts to plain dictionaries."""
        return {n: c.model_dump() for n, c in self._by_name.items()}


DEFAULT_CONTEXTS: list[BoundedContext] = [
    BoundedContext(
        name="regulatory-qa",
        domain="regulatory-qa",
        calibration_target_ece=0.03,
        coverage_target=0.70,
        risk_ceiling=0.01,
        tier_order=["haiku", "sonnet", "opus"],
    ),
    BoundedContext(
        name="retail-credit",
        domain="retail-credit",
        calibration_target_ece=0.05,
        coverage_target=0.85,
        risk_ceiling=0.03,
        tier_order=["haiku", "sonnet"],
    ),
    BoundedContext(
        name="fraud-alerts",
        domain="fraud-alerts",
        calibration_target_ece=0.07,
        coverage_target=0.95,
        risk_ceiling=0.05,
        tier_order=["haiku"],
    ),
    BoundedContext(
        name="investor-advisory",
        domain="investor-advisory",
        calibration_target_ece=0.04,
        coverage_target=0.75,
        risk_ceiling=0.02,
        tier_order=["haiku", "sonnet"],
    ),
]


def default_registry() -> ContextRegistry:
    """Return a registry populated with the four canonical contexts."""
    reg = ContextRegistry()
    for c in DEFAULT_CONTEXTS:
        reg.register(c)
    return reg


__all__ = ["DEFAULT_CONTEXTS", "BoundedContext", "ContextRegistry", "default_registry"]
