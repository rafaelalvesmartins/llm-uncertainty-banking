# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Agent-to-agent handoffs for the Bridge platform (Swarm-inspired).

Bridge agents traditionally answer in isolation: a chatbot turn returns
text, a smart-payments turn returns a :class:`PaymentIntent`. This works
until a customer mid-message *changes intent* — "qual meu saldo? ja
aproveita e paga 100 pro Joao" arrives at the chatbot, but the second
half belongs to smart_payments.

Inspired by ``openai/swarm`` (MIT): the cleanest handoff protocol is for
an agent to **return another agent**. The pipeline detects the type
swap and re-runs the same query through the new agent. No central
orchestrator decides handoffs — each agent owns the criteria for "this
isn't mine, send to X".

Banking notes
-------------

Every handoff is recorded in :class:`HandoffEvent` so the BCB 4893
audit trail explains *why* a customer's query traveled through 3 agents
instead of 1. The handoff chain is bounded (default ``max_hops=3``) to
prevent runaway loops if two agents keep handing off to each other.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import structlog

__all__ = [
    "AgentResponse",
    "HandoffChain",
    "HandoffEvent",
    "HandoffLoopError",
    "HandoffableAgent",
    "MaxHopsExceededError",
    "run_with_handoffs",
]

_LOG = structlog.get_logger("lub.bridge.handoffs")


# ---------------------------------------------------------------------------
# Public Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class HandoffableAgent(Protocol):
    """An agent that can return either a final answer or a handoff target.

    Concrete agents implement :meth:`handle`. The return discriminates:

    * ``str`` — final answer to return to the customer.
    * :class:`HandoffableAgent` — handoff target; pipeline re-runs the
      same query through that agent.
    * :class:`AgentResponse` — final answer + structured metadata.
    """

    name: str

    def handle(self, query: str, context: dict[str, Any]) -> Any:
        """Process one customer turn for the Bridge handoff pipeline.

        This is the single entry point Bridge calls for every agent in
        the chain (chatbot, smart_payments, call_center, ...). The
        return type drives the pipeline: a ``str`` or
        :class:`AgentResponse` ends the chain, while returning another
        :class:`HandoffableAgent` triggers a hop in
        :func:`run_with_handoffs`.

        Args:
            query: The customer's text, passed unchanged across hops so
                the next agent sees the original request.
            context: Mutable shared dict; agents may read prior state
                and write hints like ``context["handoff_reason"]`` to
                explain a delegation in the audit trail.

        Returns:
            ``str`` or :class:`AgentResponse` for a terminal answer, or
            another :class:`HandoffableAgent` to delegate the turn.
        """
        ...


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentResponse:
    """Structured response an agent can return when it wants to attach metadata."""

    answer: str
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HandoffEvent:
    """A single hop in the handoff chain. Audit-trail friendly."""

    from_agent: str
    to_agent: str
    reason: str
    timestamp: float


@dataclass(frozen=True)
class HandoffChain:
    """Result of a handoffs-enabled run. Includes full hop trace."""

    final_answer: str
    final_agent: str
    confidence: float
    hops: tuple[HandoffEvent, ...]
    total_duration_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def hop_count(self) -> int:
        """Return the number of handoffs Bridge performed for this turn.

        Zero means the initial agent answered directly; higher values
        feed Bridge's monitoring/analytics layers to flag chains that
        consistently hop (a signal the intent classifier or an agent's
        routing rules need tuning).
        """
        return len(self.hops)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HandoffLoopError(RuntimeError):
    """Raised when a cycle is detected (A -> B -> A within the chain)."""


class MaxHopsExceededError(RuntimeError):
    """Raised when the handoff chain exceeds ``max_hops``."""


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def run_with_handoffs(
    initial_agent: HandoffableAgent,
    query: str,
    *,
    context: dict[str, Any] | None = None,
    max_hops: int = 3,
    on_handoff: Callable[[HandoffEvent], None] | None = None,
) -> HandoffChain:
    """Drive a query through a handoff-enabled agent chain.

    Args:
        initial_agent: The first agent to receive the query.
        query: The customer's text.
        context: Mutable shared context, passed to every agent. The
            pipeline does not interpret keys; agents add to it as
            handoff hints (e.g. ``context["intent"] = "payment"``).
        max_hops: Hard cap on chain length. Defaults to 3 — empirically
            enough for chatbot -> payments -> call_center fallback,
            short enough to bound latency.
        on_handoff: Optional callback fired for each hop, useful for
            wiring into the audit trail or live UI traces without
            cluttering this function.

    Returns:
        A :class:`HandoffChain` with the final answer + every hop.

    Raises:
        HandoffLoopError: If an agent name reappears in the chain.
        MaxHopsExceededError: If more than ``max_hops`` handoffs occur.
        TypeError: If an agent returns something that isn't ``str``,
            :class:`AgentResponse`, or another :class:`HandoffableAgent`.
    """
    if context is None:
        context = {}
    start = time.perf_counter()
    hops: list[HandoffEvent] = []
    visited_names: set[str] = {initial_agent.name}
    current = initial_agent

    while True:
        result = current.handle(query, context)

        # Final answer (string or AgentResponse).
        if isinstance(result, str):
            return _finalize(result, current, 1.0, hops, start, dict(context))
        if isinstance(result, AgentResponse):
            return _finalize(
                result.answer,
                current,
                result.confidence,
                hops,
                start,
                {**context, **result.metadata},
            )

        # Handoff path.
        if not isinstance(result, HandoffableAgent):
            raise TypeError(
                f"Agent '{current.name}' returned unexpected type "
                f"{type(result).__name__}. Must return str, AgentResponse, "
                f"or HandoffableAgent."
            )

        next_agent = result
        reason = context.get("handoff_reason", f"{current.name} delegated to {next_agent.name}")
        event = HandoffEvent(
            from_agent=current.name,
            to_agent=next_agent.name,
            reason=str(reason),
            timestamp=time.time(),
        )
        hops.append(event)
        if on_handoff is not None:
            on_handoff(event)
        _LOG.info(
            "bridge.handoff",
            from_agent=event.from_agent,
            to_agent=event.to_agent,
            reason=event.reason,
            hop=len(hops),
        )

        # Cycle detection.
        if next_agent.name in visited_names:
            raise HandoffLoopError(
                f"Handoff cycle detected: {next_agent.name} already in "
                f"chain ({' -> '.join(visited_names)})"
            )
        visited_names.add(next_agent.name)

        if len(hops) >= max_hops:
            raise MaxHopsExceededError(
                f"Handoff chain exceeded max_hops={max_hops}. "
                f"Path: {' -> '.join(h.to_agent for h in hops)}"
            )

        # Clear handoff_reason so the next agent doesn't inherit it stale.
        context.pop("handoff_reason", None)
        current = next_agent


def _finalize(
    answer: str,
    final_agent: HandoffableAgent,
    confidence: float,
    hops: list[HandoffEvent],
    start: float,
    metadata: dict[str, Any],
) -> HandoffChain:
    duration_ms = (time.perf_counter() - start) * 1000
    return HandoffChain(
        final_answer=answer,
        final_agent=final_agent.name,
        confidence=confidence,
        hops=tuple(hops),
        total_duration_ms=duration_ms,
        metadata=metadata,
    )
