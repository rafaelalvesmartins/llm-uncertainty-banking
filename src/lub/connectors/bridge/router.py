# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""LLM-agnostic backend router for the Bradesco Bridge platform.

Bradesco's published architecture is explicit that *Bridge* is
LLM-agnostic — the same operator-facing surface must be able to swap
between Azure OpenAI, Anthropic, and self-hosted (Ollama / vLLM) models
without rewiring agents. This module is the selection layer that makes
that promise concrete: given a query and a set of requirements
(maximum cost, maximum latency, required capabilities), it picks the
cheapest still-eligible backend and exposes a deterministic failover
path when the primary choice errors or is circuit-broken.

The router intentionally sits *below* the existing
:class:`lub.bridge.BridgePlatform`/:class:`lub.bridge.platform.BridgePlatform`
agent layer and *above* the wire-level wrappers in
:mod:`lub.wrappers` / :mod:`lub.integrations`. It is complementary to
:class:`lub.orchestration.TieredRouter`:

* :class:`~lub.orchestration.TieredRouter` cascades through tiers using
  uncertainty as the escalation signal (cheap-then-expensive on the
  *same* answer).
* :class:`BridgeRouter` (this module) is a fan-out *selector* — given
  one query and a SLO, return the best backend handle for that
  individual call. It does not produce an answer; it returns a backend
  the caller can then drive.

Banking / compliance notes
--------------------------

* Every routing decision is logged through ``structlog`` with the
  backend name, decision rationale, and (when relevant) the failure
  classification. This is the evidence stream a BCB 4893 or SR 11-7
  reviewer follows when asked "why did this customer query hit
  Anthropic at 14:03 instead of Azure?".
* The circuit-breaker state is observable through
  :meth:`BridgeRouter.health` so a /healthz endpoint can surface a
  partially-degraded routing tier before customers notice.
* The router never returns a backend that is currently circuit-broken
  unless the caller explicitly opts into the unhealthy pool via
  :meth:`BridgeRouter.route` with ``include_unhealthy=True`` (used by
  drain/probe workflows, not by customer traffic).

This module is dependency-light: it builds on
:class:`lub.protocols.BackendProto` so any backend that exposes a
``generate(prompt: str) -> str`` method qualifies, and on
:mod:`pydantic` for backend-config validation.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator

from lub.protocols import BackendProto

__all__ = [
    "BackendConfig",
    "BackendUnavailableError",
    "BridgeRouter",
    "Capability",
    "NoEligibleBackendError",
    "RouteDecision",
    "RouteRequirements",
]

_LOG = structlog.get_logger("lub.bridge.router")


# ---------------------------------------------------------------------------
# Public value objects
# ---------------------------------------------------------------------------


class Capability(StrEnum):
    """Capability tags a backend may advertise.

    Bradesco's three flagship surfaces use different feature subsets:
    the chatbot needs only text; the call-center surface needs voice;
    Smart Payments needs vision (boleto photos) and function calling
    (PIX/TED dispatch). Capabilities here are the routing axis that
    keeps a vision-required query from landing on a text-only model.
    """

    TEXT_GENERATION = "text_generation"
    FUNCTION_CALLING = "function_calling"
    VISION = "vision"
    VOICE = "voice"
    EMBEDDINGS = "embeddings"
    LONG_CONTEXT = "long_context"
    PORTUGUESE = "portuguese"


class BackendConfig(BaseModel):
    """Routing metadata for one registered backend.

    Attributes
    ----------
    name:
        Stable identifier (e.g. ``"azure-gpt4o"``, ``"anthropic-sonnet-4-6"``,
        ``"local-llama3-70b"``). Used in logs and audit trails — must be
        unique within a single :class:`BridgeRouter`.
    cost_per_1k_tokens:
        Approximate USD cost per 1000 output tokens. Banks negotiate
        custom rates so this is operator-supplied, not hard-coded.
    avg_latency_ms:
        Recent average end-to-end latency, milliseconds. Used as the
        *predicted* latency by :class:`BridgeRouter` until the EWMA
        observation overrides it.
    capabilities:
        Set of :class:`Capability` tags the backend supports. Routing
        with a required capability that no registered backend
        advertises raises :class:`NoEligibleBackendError`.
    priority:
        Tie-breaker when two backends are otherwise equal. Higher wins.
        Lets operators pin a preferred provider for regulatory reasons
        (e.g. data-residency: prefer the Azure Brazil region tenant).
    enabled:
        Soft flag for operator-driven drains. A disabled backend is
        skipped during routing without being marked unhealthy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., min_length=1, max_length=128)
    cost_per_1k_tokens: float = Field(..., ge=0.0)
    avg_latency_ms: float = Field(..., gt=0.0)
    capabilities: frozenset[Capability] = Field(default_factory=frozenset)
    priority: int = Field(default=0)
    enabled: bool = Field(default=True)

    @field_validator("capabilities", mode="before")
    @classmethod
    def _coerce_capabilities(cls, value: Any) -> frozenset[Capability]:
        """Accept any iterable of capabilities / strings and normalise."""
        if value is None:
            return frozenset()
        if isinstance(value, Capability):
            return frozenset({value})
        if isinstance(value, str):
            return frozenset({Capability(value)})
        return frozenset(Capability(v) if not isinstance(v, Capability) else v for v in value)


@dataclass(frozen=True)
class RouteRequirements:
    """Caller-supplied SLO/feature constraints for a single query.

    A backend qualifies when it satisfies *every* set requirement:
    cost <= ``max_cost_per_1k_tokens``, latency <= ``max_latency_ms``,
    and capabilities cover ``required_capabilities``. ``None`` means
    "don't constrain on this axis".

    Optimisation axis
    -----------------

    Among qualifying backends, the router picks the one that minimises
    ``optimise`` (``"cost"`` by default — Bridge runs at large scale,
    so cost is the dominant operational lever once the SLO is met).
    Ties are broken by :attr:`BackendConfig.priority` (higher first)
    then by backend name (alphabetical, for determinism in tests).
    """

    max_cost_per_1k_tokens: float | None = None
    max_latency_ms: float | None = None
    required_capabilities: frozenset[Capability] = field(default_factory=frozenset)
    optimise: str = "cost"

    def __post_init__(self) -> None:
        if self.optimise not in {"cost", "latency"}:
            raise ValueError(f"optimise must be 'cost' or 'latency', got {self.optimise!r}")
        if self.max_cost_per_1k_tokens is not None and self.max_cost_per_1k_tokens < 0:
            raise ValueError("max_cost_per_1k_tokens must be >= 0")
        if self.max_latency_ms is not None and self.max_latency_ms <= 0:
            raise ValueError("max_latency_ms must be > 0")


@dataclass(frozen=True)
class RouteDecision:
    """The router's selection plus the reasoning attached to it.

    Returned by :meth:`BridgeRouter.route` and :meth:`BridgeRouter.failover`.
    The audit trail keeps the *why* alongside the *what*, so a compliance
    reviewer can answer "why this backend?" without replaying production
    traffic.
    """

    backend_name: str
    backend: BackendProto
    config: BackendConfig
    rationale: str
    eligible_backends: tuple[str, ...]
    excluded_backends: tuple[Mapping[str, str], ...] = field(default_factory=tuple)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class NoEligibleBackendError(RuntimeError):
    """No registered backend satisfies the supplied :class:`RouteRequirements`.

    Raised by :meth:`BridgeRouter.route` and :meth:`BridgeRouter.failover`
    rather than returning ``None`` so the caller cannot accidentally
    dispatch to an unset variable. Banking software prefers loud
    failures here — silently degrading from "vision-capable backend
    needed" to "any backend" could route a boleto-photo request to a
    text-only model and produce a confident but wrong answer.
    """


class BackendUnavailableError(RuntimeError):
    """Raised when a named backend is unknown or currently circuit-broken."""


# ---------------------------------------------------------------------------
# Internal book-keeping
# ---------------------------------------------------------------------------


@dataclass
class _BackendEntry:
    """Mutable runtime state attached to a registered backend.

    Not part of the public API — :class:`BridgeRouter` owns instances of
    this and exposes them only via :meth:`BridgeRouter.health`.
    """

    backend: BackendProto
    config: BackendConfig
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    total_calls: int = 0
    total_failures: int = 0
    ewma_latency_ms: float | None = None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class BridgeRouter:
    """LLM-agnostic backend selector with automatic failover.

    The router owns a registry of named backends, each tagged with cost,
    latency, and capabilities (:class:`BackendConfig`). For each query
    the caller asks for a backend matching a :class:`RouteRequirements`
    SLO; the router returns the cheapest (or lowest-latency) backend
    that still satisfies the SLO and is not currently circuit-broken.

    Failure handling
    ----------------

    Callers are expected to invoke :meth:`record_failure` after a
    backend raises, and :meth:`record_success` after a successful call.
    The router uses a simple consecutive-failure circuit breaker:
    after ``failure_threshold`` consecutive failures, the backend is
    parked for ``cooldown_seconds`` and excluded from routing decisions.
    A single successful call resets the counter. This deliberately
    mirrors the avoid-shed-admit pattern operators already use for
    downstream banking APIs, so the router's behaviour is legible to
    the on-call SRE.

    Parameters
    ----------
    failure_threshold:
        Consecutive failures before a backend trips its breaker.
    cooldown_seconds:
        How long a tripped backend stays parked before being eligible
        again. Subsequent failures during cooldown extend the parking
        window so a flapping backend doesn't oscillate into traffic.
    latency_ewma_alpha:
        Exponential-moving-average smoothing factor in (0, 1] used by
        :meth:`record_success` when observed latencies are reported.
        ``1.0`` means "trust the last observation"; ``0.2`` (default)
        weights the last sample at 20%.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
        latency_ewma_alpha: float = 0.2,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if cooldown_seconds < 0.0:
            raise ValueError("cooldown_seconds must be >= 0")
        if not 0.0 < latency_ewma_alpha <= 1.0:
            raise ValueError("latency_ewma_alpha must be in (0, 1]")

        self._entries: dict[str, _BackendEntry] = {}
        self._failure_threshold = int(failure_threshold)
        self._cooldown_seconds = float(cooldown_seconds)
        self._alpha = float(latency_ewma_alpha)

        _LOG.info(
            "bridge.router.initialized",
            failure_threshold=self._failure_threshold,
            cooldown_seconds=self._cooldown_seconds,
            latency_ewma_alpha=self._alpha,
        )

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #

    def add_backend(
        self,
        name: str,
        backend: BackendProto,
        config: BackendConfig | None = None,
        *,
        replace: bool = False,
    ) -> None:
        """Register ``backend`` under ``name``.

        Parameters
        ----------
        name:
            Stable identifier. When ``config`` is also supplied, the
            ``name`` argument and ``config.name`` must agree — we keep
            both so call sites can supply just a name plus the bare
            backend object during prototyping.
        backend:
            Object implementing :class:`lub.protocols.BackendProto`
            (a ``generate(prompt: str) -> str`` method, at minimum).
        config:
            Routing metadata. If omitted, a default config is built
            with conservative placeholders (cost=0.0, latency=1000ms,
            no advertised capabilities) — useful for tests, but
            production deployments should always supply a real config.
        replace:
            When ``False`` (default), re-registering a known name
            raises. Pass ``True`` to deliberately swap a backend
            (canary rotation, secret rotation, etc.). Always logged.
        """
        if not callable(getattr(backend, "generate", None)):
            raise TypeError(
                f"backend for {name!r} must expose a callable generate() method, "
                f"got {type(backend).__name__}"
            )

        cfg = self._coerce_config(name, config)

        already = name in self._entries
        if already and not replace:
            raise ValueError(
                f"Backend {name!r} is already registered; pass replace=True to override."
            )

        self._entries[name] = _BackendEntry(backend=backend, config=cfg)
        if already:
            _LOG.warning("bridge.router.backend_replaced", name=name)
        else:
            _LOG.info(
                "bridge.router.backend_registered",
                name=name,
                cost_per_1k_tokens=cfg.cost_per_1k_tokens,
                avg_latency_ms=cfg.avg_latency_ms,
                capabilities=sorted(c.value for c in cfg.capabilities),
                priority=cfg.priority,
                enabled=cfg.enabled,
            )

    def remove_backend(self, name: str) -> None:
        """Unregister ``name``. Raises :class:`BackendUnavailableError` if unknown."""
        if name not in self._entries:
            raise BackendUnavailableError(f"backend {name!r} is not registered")
        del self._entries[name]
        _LOG.info("bridge.router.backend_removed", name=name)

    def set_enabled(self, name: str, enabled: bool) -> None:
        """Soft-disable or re-enable a backend without dropping its config.

        Used for operator-driven drains (e.g. before rotating an Azure
        key). Distinct from the circuit-breaker, which is automatic.
        """
        entry = self._require_entry(name)
        entry.config = entry.config.model_copy(update={"enabled": enabled})
        _LOG.info("bridge.router.backend_enabled_changed", name=name, enabled=enabled)

    # ------------------------------------------------------------------ #
    # Routing
    # ------------------------------------------------------------------ #

    def route(
        self,
        query: str,
        requirements: RouteRequirements | None = None,
        *,
        include_unhealthy: bool = False,
    ) -> RouteDecision:
        """Pick the best backend for ``query`` under ``requirements``.

        Returns a :class:`RouteDecision` packaging the chosen backend
        with the reasoning. Never returns ``None`` — when no backend
        qualifies, raises :class:`NoEligibleBackendError` so the
        compliance audit trail records the dispatch failure rather
        than seeing a silently-substituted fallback.
        """
        reqs = requirements if requirements is not None else RouteRequirements()
        eligible, excluded = self._partition(reqs, include_unhealthy=include_unhealthy)

        if not eligible:
            self._log_no_backend(query, reqs, excluded)
            raise NoEligibleBackendError(self._format_no_backend_message(reqs, excluded))

        winner = self._pick_winner(eligible, reqs)
        rationale = self._build_rationale(winner, reqs, eligible)

        decision = RouteDecision(
            backend_name=winner.config.name,
            backend=winner.backend,
            config=winner.config,
            rationale=rationale,
            eligible_backends=tuple(e.config.name for e in eligible),
            excluded_backends=tuple(excluded),
        )
        _LOG.info(
            "bridge.router.route_decided",
            query_chars=len(query),
            chosen=decision.backend_name,
            eligible=decision.eligible_backends,
            excluded=[e["name"] for e in decision.excluded_backends],
            optimise=reqs.optimise,
        )
        return decision

    def failover(
        self,
        query: str,
        failed_backend: str,
        requirements: RouteRequirements | None = None,
    ) -> RouteDecision:
        """Re-route ``query`` away from ``failed_backend``.

        Marks the named backend as having just failed (incrementing
        its circuit-breaker counter) and then runs the same selection
        logic as :meth:`route` while explicitly excluding it from the
        candidate pool, regardless of whether the failure tripped the
        breaker. This guarantees the caller never gets the same
        backend back on an immediate retry.

        Raises :class:`NoEligibleBackendError` when the exclusion
        leaves no qualifying backend — callers should surface that as
        a human escalation rather than retrying further.
        """
        if failed_backend not in self._entries:
            raise BackendUnavailableError(
                f"failover requested for unknown backend {failed_backend!r}"
            )

        self.record_failure(failed_backend)

        reqs = requirements if requirements is not None else RouteRequirements()
        eligible, excluded = self._partition(
            reqs,
            include_unhealthy=False,
            extra_exclusions={failed_backend: "explicit_failover"},
        )

        if not eligible:
            self._log_no_backend(query, reqs, excluded, failover_from=failed_backend)
            raise NoEligibleBackendError(
                f"failover from {failed_backend!r} exhausted: "
                + self._format_no_backend_message(reqs, excluded)
            )

        winner = self._pick_winner(eligible, reqs)
        rationale = f"failover from {failed_backend!r}: " + self._build_rationale(
            winner, reqs, eligible
        )

        decision = RouteDecision(
            backend_name=winner.config.name,
            backend=winner.backend,
            config=winner.config,
            rationale=rationale,
            eligible_backends=tuple(e.config.name for e in eligible),
            excluded_backends=tuple(excluded),
        )
        _LOG.warning(
            "bridge.router.failover",
            query_chars=len(query),
            failed=failed_backend,
            chosen=decision.backend_name,
            eligible=decision.eligible_backends,
        )
        return decision

    # ------------------------------------------------------------------ #
    # Feedback hooks
    # ------------------------------------------------------------------ #

    def record_success(
        self,
        name: str,
        *,
        observed_latency_ms: float | None = None,
    ) -> None:
        """Tell the router that a call to ``name`` succeeded.

        Clears the consecutive-failure counter, lifts any active
        cooldown, and optionally updates the EWMA latency estimate
        used for future routing decisions. Call this from the wrapper
        that drives :class:`BackendProto.generate` so the router's
        view of "healthy" stays close to wire-level reality.
        """
        entry = self._require_entry(name)
        entry.total_calls += 1
        entry.consecutive_failures = 0
        entry.cooldown_until = 0.0
        if observed_latency_ms is not None and observed_latency_ms > 0:
            if entry.ewma_latency_ms is None:
                entry.ewma_latency_ms = float(observed_latency_ms)
            else:
                entry.ewma_latency_ms = (
                    self._alpha * float(observed_latency_ms)
                    + (1.0 - self._alpha) * entry.ewma_latency_ms
                )
        _LOG.debug(
            "bridge.router.success",
            name=name,
            observed_latency_ms=observed_latency_ms,
            ewma_latency_ms=entry.ewma_latency_ms,
        )

    def record_failure(
        self,
        name: str,
        *,
        error: str | None = None,
    ) -> None:
        """Tell the router that a call to ``name`` failed.

        Increments the consecutive-failure counter and trips the
        circuit breaker when the threshold is reached. ``error`` is
        an optional short classification (``"timeout"``, ``"5xx"``,
        ``"auth"``, ...) that lands in the structured log so SRE
        dashboards can split failures by mode.
        """
        entry = self._require_entry(name)
        entry.total_calls += 1
        entry.total_failures += 1
        entry.consecutive_failures += 1
        tripped = entry.consecutive_failures >= self._failure_threshold
        if tripped:
            entry.cooldown_until = time.monotonic() + self._cooldown_seconds
            _LOG.warning(
                "bridge.router.circuit_open",
                name=name,
                consecutive_failures=entry.consecutive_failures,
                cooldown_seconds=self._cooldown_seconds,
                error=error,
            )
        else:
            _LOG.info(
                "bridge.router.failure",
                name=name,
                consecutive_failures=entry.consecutive_failures,
                threshold=self._failure_threshold,
                error=error,
            )

    # ------------------------------------------------------------------ #
    # Inspection
    # ------------------------------------------------------------------ #

    @property
    def backends(self) -> tuple[str, ...]:
        """Names of all currently-registered backends (any health state)."""
        return tuple(self._entries)

    def get_config(self, name: str) -> BackendConfig:
        """Return the current :class:`BackendConfig` for ``name``."""
        return self._require_entry(name).config

    def is_healthy(self, name: str) -> bool:
        """``True`` when ``name`` is enabled and not in cooldown."""
        entry = self._require_entry(name)
        return entry.config.enabled and entry.cooldown_until <= time.monotonic()

    def health(self) -> dict[str, dict[str, Any]]:
        """Snapshot of per-backend health for /healthz endpoints."""
        now = time.monotonic()
        snapshot: dict[str, dict[str, Any]] = {}
        for name, entry in self._entries.items():
            in_cooldown = entry.cooldown_until > now
            snapshot[name] = {
                "enabled": entry.config.enabled,
                "healthy": entry.config.enabled and not in_cooldown,
                "consecutive_failures": entry.consecutive_failures,
                "total_calls": entry.total_calls,
                "total_failures": entry.total_failures,
                "cooldown_remaining_seconds": (
                    max(0.0, entry.cooldown_until - now) if in_cooldown else 0.0
                ),
                "ewma_latency_ms": entry.ewma_latency_ms,
                "cost_per_1k_tokens": entry.config.cost_per_1k_tokens,
                "capabilities": sorted(c.value for c in entry.config.capabilities),
            }
        return snapshot

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def _coerce_config(name: str, config: BackendConfig | None) -> BackendConfig:
        """Build or validate a config consistent with the supplied name."""
        if config is None:
            return BackendConfig(
                name=name,
                cost_per_1k_tokens=0.0,
                avg_latency_ms=1000.0,
            )
        if config.name != name:
            raise ValueError(
                f"add_backend name {name!r} disagrees with config.name {config.name!r}"
            )
        return config

    def _require_entry(self, name: str) -> _BackendEntry:
        """Look up an entry by name, raising :class:`BackendUnavailableError`."""
        entry = self._entries.get(name)
        if entry is None:
            raise BackendUnavailableError(f"backend {name!r} is not registered")
        return entry

    def _effective_latency(self, entry: _BackendEntry) -> float:
        """Observed EWMA latency when present, otherwise the configured estimate."""
        return (
            entry.ewma_latency_ms
            if entry.ewma_latency_ms is not None
            else entry.config.avg_latency_ms
        )

    def _partition(
        self,
        reqs: RouteRequirements,
        *,
        include_unhealthy: bool,
        extra_exclusions: Mapping[str, str] | None = None,
    ) -> tuple[list[_BackendEntry], list[Mapping[str, str]]]:
        """Split registered backends into eligible / excluded lists.

        ``extra_exclusions`` is a name → reason map for caller-forced
        exclusions (used by :meth:`failover` to skip the failed
        backend regardless of breaker state).
        """
        now = time.monotonic()
        eligible: list[_BackendEntry] = []
        excluded: list[Mapping[str, str]] = []
        extra = dict(extra_exclusions or {})

        for name, entry in self._entries.items():
            if name in extra:
                excluded.append({"name": name, "reason": extra[name]})
                continue
            if not entry.config.enabled:
                excluded.append({"name": name, "reason": "disabled"})
                continue
            if not include_unhealthy and entry.cooldown_until > now:
                excluded.append({"name": name, "reason": "circuit_open"})
                continue
            if reqs.required_capabilities and not reqs.required_capabilities.issubset(
                entry.config.capabilities
            ):
                missing = sorted(
                    c.value for c in reqs.required_capabilities - entry.config.capabilities
                )
                excluded.append(
                    {"name": name, "reason": f"missing_capabilities:{','.join(missing)}"}
                )
                continue
            if (
                reqs.max_cost_per_1k_tokens is not None
                and entry.config.cost_per_1k_tokens > reqs.max_cost_per_1k_tokens
            ):
                excluded.append({"name": name, "reason": "cost_exceeds_slo"})
                continue
            if (
                reqs.max_latency_ms is not None
                and self._effective_latency(entry) > reqs.max_latency_ms
            ):
                excluded.append({"name": name, "reason": "latency_exceeds_slo"})
                continue
            eligible.append(entry)

        return eligible, excluded

    def _pick_winner(
        self,
        eligible: Iterable[_BackendEntry],
        reqs: RouteRequirements,
    ) -> _BackendEntry:
        """Apply the optimisation axis and tie-breakers."""

        def sort_key(entry: _BackendEntry) -> tuple[float, int, str]:
            primary = (
                entry.config.cost_per_1k_tokens
                if reqs.optimise == "cost"
                else self._effective_latency(entry)
            )
            return (primary, -entry.config.priority, entry.config.name)

        return sorted(eligible, key=sort_key)[0]

    def _build_rationale(
        self,
        winner: _BackendEntry,
        reqs: RouteRequirements,
        eligible: Iterable[_BackendEntry],
    ) -> str:
        """Human-readable explanation attached to the :class:`RouteDecision`."""
        n = sum(1 for _ in eligible)
        axis = reqs.optimise
        primary = (
            winner.config.cost_per_1k_tokens if axis == "cost" else self._effective_latency(winner)
        )
        units = "USD/1k tok" if axis == "cost" else "ms"
        return (
            f"chose {winner.config.name!r} among {n} eligible backend(s) "
            f"by minimum {axis} ({primary:.4f} {units}); "
            f"priority={winner.config.priority}, "
            f"capabilities={sorted(c.value for c in winner.config.capabilities)}"
        )

    def _format_no_backend_message(
        self,
        reqs: RouteRequirements,
        excluded: Iterable[Mapping[str, str]],
    ) -> str:
        """Compose the :class:`NoEligibleBackendError` message."""
        reasons = ", ".join(f"{e['name']}={e['reason']}" for e in excluded) or "none"
        caps = sorted(c.value for c in reqs.required_capabilities)
        return (
            "no backend satisfies requirements "
            f"(max_cost={reqs.max_cost_per_1k_tokens}, "
            f"max_latency={reqs.max_latency_ms}, "
            f"required_capabilities={caps}); "
            f"excluded=[{reasons}]"
        )

    def _log_no_backend(
        self,
        query: str,
        reqs: RouteRequirements,
        excluded: Iterable[Mapping[str, str]],
        *,
        failover_from: str | None = None,
    ) -> None:
        """Emit a structured log entry when routing finds no candidate."""
        _LOG.error(
            "bridge.router.no_eligible_backend",
            query_chars=len(query),
            failover_from=failover_from,
            max_cost=reqs.max_cost_per_1k_tokens,
            max_latency_ms=reqs.max_latency_ms,
            required_capabilities=sorted(c.value for c in reqs.required_capabilities),
            optimise=reqs.optimise,
            excluded=list(excluded),
        )
