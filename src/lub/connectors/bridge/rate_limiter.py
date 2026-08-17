# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Rate limiter for the Bridge API — protects LLM backends from overload.

Implements a classic **token-bucket** rate limiter keyed by
``(customer_id, channel)`` so the three Bradesco Bridge surfaces
(WhatsApp chatbot, mobile/web chat, call-center copilot) can share a
single LLM pool without one runaway client starving the others.

Why this exists
---------------

The reference Bradesco deployment serves *millions of customers daily*
across WhatsApp, mobile, web, and the call-center copilot. Azure OpenAI
quotas, Anthropic TPM limits, and on-prem GPU capacity are all finite,
and every regulated banking workflow that goes through Bridge competes
for the same backend pool. A bad actor (or a buggy retry loop in a
client app) can drain that pool in seconds, which:

* breaks SR 11-7's *model availability* expectation,
* breaches BCB 4893's *operational-resilience* requirement,
* and — most directly — costs the bank money on per-token billing.

A per-customer / per-channel limiter caps each principal independently
so a single misbehaving session cannot affect the 90%-retention SLA the
platform reports against. The limiter is *advisory* — :meth:`allow`
returns a boolean and the caller decides whether to drop, queue, or
escalate; this keeps the rate-limiter free of policy concerns and lets
:mod:`lub.bridge.platform` apply different responses on different
channels (e.g. WhatsApp queues, call-center escalates immediately).

Algorithm
---------

Token-bucket, not leaky-bucket: bursts up to ``burst_size`` are
permitted (a customer can fire several quick follow-up questions),
while the long-run rate is capped at ``requests_per_minute``. Tokens
refill *lazily* on each call, so the limiter has no background thread
and no per-bucket timer — important because at Bradesco scale we may
hold hundreds of thousands of buckets in memory.

Concurrency
-----------

A single :class:`threading.Lock` guards the bucket map. The lock is
held only for O(1) work per call, so contention is negligible even at
the multi-thousand-RPS sustained throughput the reference deployment
sees. This mirrors the lock discipline already used by
:class:`~lub.bridge.session.InMemorySessionStore`.

Memory hygiene
--------------

Idle buckets are reaped on demand by :meth:`prune` (callers wire this
to a periodic task) so the map does not grow unboundedly. A bucket is
considered idle when it has been full (``tokens >= burst_size``) and
untouched for more than ``idle_ttl_seconds``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Final

import structlog

from lub.connectors.bridge.session import Channel

__all__ = [
    "RateLimitConfig",
    "RateLimitStats",
    "RateLimiter",
]

log = structlog.get_logger(__name__)


_SECONDS_PER_MINUTE: Final[int] = 60


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RateLimitConfig:
    """Token-bucket parameters.

    Attributes
    ----------
    requests_per_minute:
        Long-run cap on requests per ``(customer_id, channel)`` key.
        Translated internally to a per-second token refill rate.
    burst_size:
        Bucket capacity. The maximum number of requests a single
        principal can fire back-to-back before the steady-state rate
        kicks in. Defaults to ``requests_per_minute`` (i.e. up to one
        minute of headroom in a burst).
    idle_ttl_seconds:
        Buckets full and untouched for longer than this are eligible
        for :meth:`RateLimiter.prune`. Defaults to five minutes, which
        matches the BCB-4893 inactivity threshold most pilots use.
    """

    requests_per_minute: int
    burst_size: int = 0
    idle_ttl_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.requests_per_minute <= 0:
            raise ValueError(
                f"requests_per_minute must be positive, got {self.requests_per_minute}"
            )
        if self.burst_size < 0:
            raise ValueError(f"burst_size must be non-negative, got {self.burst_size}")
        if self.idle_ttl_seconds < 0:
            raise ValueError(f"idle_ttl_seconds must be non-negative, got {self.idle_ttl_seconds}")
        if self.burst_size == 0:
            object.__setattr__(self, "burst_size", self.requests_per_minute)

    @property
    def tokens_per_second(self) -> float:
        """Refill rate derived from :attr:`requests_per_minute`."""
        return self.requests_per_minute / _SECONDS_PER_MINUTE


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RateLimitStats:
    """Point-in-time view of limiter activity.

    Surfaces the numbers a BCBS 239 risk-data aggregator needs to verify
    that the automated channel is operating inside its declared envelope.
    """

    total_requests: int
    allowed: int
    rejected: int
    active_buckets: int
    config: RateLimitConfig

    @property
    def rejection_rate(self) -> float:
        """Share of requests rejected by the limiter (0.0 — 1.0)."""
        if self.total_requests == 0:
            return 0.0
        return self.rejected / self.total_requests

    @property
    def allow_rate(self) -> float:
        """Share of requests permitted by the limiter (0.0 — 1.0)."""
        if self.total_requests == 0:
            return 1.0
        return self.allowed / self.total_requests


# ---------------------------------------------------------------------------
# Internal bucket
# ---------------------------------------------------------------------------


@dataclass
class _Bucket:
    """Lazy token bucket. Refills on access; never on a timer."""

    tokens: float
    last_refill: float

    def refill(self, capacity: int, rate: float, now: float) -> None:
        """Top up tokens based on time elapsed since the last refill.

        Called on every Bridge request to lazily replenish the bucket
        before :meth:`try_consume` checks whether the call fits inside
        the customer's budget. Keeping the refill on the access path
        (rather than on a background timer) is what lets the Bridge hub
        hold hundreds of thousands of per-customer buckets cheaply
        across the WhatsApp, mobile, and call-center channels.

        Args
        ----
        capacity:
            Upper bound on ``tokens`` after refill — the bucket never
            exceeds the configured ``burst_size``.
        rate:
            Tokens added per second (derived from
            :attr:`RateLimitConfig.tokens_per_second`).
        now:
            Current monotonic clock reading; passed in so the limiter
            stays deterministic under the injected test clock.
        """
        elapsed = max(0.0, now - self.last_refill)
        self.tokens = min(float(capacity), self.tokens + elapsed * rate)
        self.last_refill = now

    def try_consume(self, capacity: int, rate: float, now: float) -> bool:
        """Refill then attempt to spend one token for a Bridge request.

        Hot path invoked by :meth:`RateLimiter.allow` for every customer
        turn that flows through the Bridge hub — chatbot, smart-payments,
        and call-center copilot all go through here before reaching the
        LLM wrappers. Returning ``False`` signals the hub to apply its
        per-channel back-pressure policy (queue on WhatsApp, escalate to
        a human on the call center).

        Args
        ----
        capacity, rate, now:
            Forwarded to :meth:`refill`; see that method for semantics.

        Returns
        -------
        bool
            ``True`` if a token was available and consumed; ``False`` if
            the bucket was empty after refill.
        """
        self.refill(capacity, rate, now)
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    def seconds_until_token(self, capacity: int, rate: float, now: float) -> float:
        """Compute how long the caller must wait for the next token.

        Backs :meth:`RateLimiter.wait`, which Bridge surfaces to the
        platform layer so the hub can tell a WhatsApp client *"retry in
        N seconds"* without spinning. The method does not sleep — it
        only reports — which keeps policy decisions (block, queue,
        escalate) in the Bridge platform where they belong.

        Args
        ----
        capacity, rate, now:
            Forwarded to :meth:`refill`; see that method for semantics.

        Returns
        -------
        float
            Seconds until the bucket holds at least one token. Returns
            ``0.0`` when a token is already available and ``inf`` when
            ``rate`` is zero (a misconfigured bucket that will never
            refill).
        """
        self.refill(capacity, rate, now)
        if self.tokens >= 1.0:
            return 0.0
        deficit = 1.0 - self.tokens
        return deficit / rate if rate > 0 else float("inf")


# ---------------------------------------------------------------------------
# Limiter
# ---------------------------------------------------------------------------


_Key = tuple[str, str]


class RateLimiter:
    """Thread-safe per-customer / per-channel token-bucket limiter.

    Parameters
    ----------
    config:
        Bucket parameters. The same parameters apply to every key —
        differentiated limits across channels are achieved by composing
        multiple :class:`RateLimiter` instances rather than overloading
        a single one. This keeps the audit story per-channel clean for
        SR 11-7 reviews.
    clock:
        Injectable wall-clock (seconds since epoch). Defaults to
        :func:`time.monotonic`, which is immune to NTP jumps — important
        because a backwards step could otherwise reset every bucket.
    """

    def __init__(
        self,
        config: RateLimitConfig,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._config = config
        self._clock = clock if clock is not None else time.monotonic
        self._buckets: dict[_Key, _Bucket] = {}
        self._lock = threading.Lock()
        self._total = 0
        self._allowed = 0
        self._rejected = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def config(self) -> RateLimitConfig:
        """Read-only view of the configured parameters."""
        return self._config

    def allow(self, customer_id: str, channel: Channel | str) -> bool:
        """Attempt to consume one token for ``(customer_id, channel)``.

        Returns ``True`` if the request is within the allowed budget,
        ``False`` otherwise. Callers decide what to do on rejection —
        :mod:`lub.bridge.platform` typically routes the customer to a
        queue or to a human operator depending on channel.
        """
        if not customer_id:
            raise ValueError("customer_id must be a non-empty string")
        key = self._key(customer_id, channel)
        now = self._clock()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=float(self._config.burst_size), last_refill=now)
                self._buckets[key] = bucket
            permitted = bucket.try_consume(
                self._config.burst_size, self._config.tokens_per_second, now
            )
            self._total += 1
            if permitted:
                self._allowed += 1
            else:
                self._rejected += 1
        if not permitted:
            log.info(
                "rate_limit.rejected",
                customer_id=customer_id,
                channel=str(channel),
                rpm=self._config.requests_per_minute,
                burst=self._config.burst_size,
            )
        return permitted

    def wait(self, customer_id: str, channel: Channel | str) -> float:
        """Return seconds the caller must wait before the next ``allow``.

        Does **not** sleep — the caller chooses whether to block, queue,
        or escalate. Returns ``0.0`` when a token is already available.
        """
        if not customer_id:
            raise ValueError("customer_id must be a non-empty string")
        key = self._key(customer_id, channel)
        now = self._clock()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return 0.0
            return bucket.seconds_until_token(
                self._config.burst_size, self._config.tokens_per_second, now
            )

    def stats(self) -> RateLimitStats:
        """Snapshot the limiter's counters."""
        with self._lock:
            return RateLimitStats(
                total_requests=self._total,
                allowed=self._allowed,
                rejected=self._rejected,
                active_buckets=len(self._buckets),
                config=self._config,
            )

    def reset(self) -> None:
        """Drop all buckets and counters. Intended for tests."""
        with self._lock:
            self._buckets.clear()
            self._total = 0
            self._allowed = 0
            self._rejected = 0

    def prune(self) -> int:
        """Evict full + idle buckets. Returns the number reaped.

        Safe to call from a periodic task. A bucket is considered idle
        when it is at full capacity *and* untouched for longer than
        :attr:`RateLimitConfig.idle_ttl_seconds` — a half-empty bucket
        is never reaped because doing so would silently restore burst
        budget the customer had already spent.
        """
        now = self._clock()
        ttl = self._config.idle_ttl_seconds
        rate = self._config.tokens_per_second
        capacity = self._config.burst_size
        reaped = 0
        with self._lock:
            for key in self._stale_keys(now, ttl, rate, capacity):
                del self._buckets[key]
                reaped += 1
        if reaped:
            log.debug("rate_limit.pruned", reaped=reaped)
        return reaped

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _key(customer_id: str, channel: Channel | str) -> _Key:
        ch = channel.value if isinstance(channel, Channel) else str(channel)
        return (customer_id, ch)

    def _stale_keys(self, now: float, ttl: float, rate: float, capacity: int) -> Iterator[_Key]:
        for key, bucket in self._buckets.items():
            # Refill virtually to check current fill without mutating state
            # before we know we're keeping the bucket.
            elapsed = max(0.0, now - bucket.last_refill)
            projected = min(float(capacity), bucket.tokens + elapsed * rate)
            if projected >= capacity and elapsed >= ttl:
                yield key
