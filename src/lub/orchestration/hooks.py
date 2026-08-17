# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Pre/post hook system around ``pipeline.answer``.

Hooks run *around* a pipeline call and may read / mutate a shared
``state`` dict. They cannot change the prompt or the result in place
(those are immutable), but a post-hook can observe the result and,
for example, write it to the ledger.

Two hook surfaces in lub: this module is the **observer** (no
mutation, ledger / telemetry / evidence indexing); :mod:`lub.rails`
is the **filter** (rewrites prompt / result for one call).

Why hooks are sync
------------------

The pipeline does NOT await hook I/O. Hooks must return quickly so
that adding telemetry never moves the latency budget of the pipeline.
Anything that needs network or disk I/O must be pushed to a
background queue / executor by the hook itself.

Example: a post-hook that ships results to the ledger.

The wrong pattern (blocks the pipeline on every call)::

    def slow_audit_hook(ctx):
        ledger.log_answer(...)         # network or disk -- BAD
        ledger.log_score(...)          # blocks pipeline.answer

The right pattern (background-queue the I/O, return immediately)::

    import queue, threading

    _audit_queue = queue.Queue(maxsize=1024)

    def _drain_audit_queue():
        while True:
            ctx = _audit_queue.get()
            try:
                if ctx.result is not None:
                    ledger.log_answer(...)
                    ledger.log_score(...)
            finally:
                _audit_queue.task_done()

    threading.Thread(target=_drain_audit_queue, daemon=True).start()

    def fast_audit_hook(ctx):
        try:
            _audit_queue.put_nowait(ctx)
        except queue.Full:
            _LOG.warning("hooks.audit_queue_full")  # bounded backpressure

    registry.add_post(fast_audit_hook)

For pure-async pipelines, replace queue.Queue / Thread with
asyncio.Queue + asyncio.create_task; the hook itself stays sync-and-fast
(put_nowait) because Hook is a sync Protocol on purpose.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import structlog

from lub.types import UncertaintyResult

if TYPE_CHECKING:
    from lub.protocols import PipelineProto

_LOG = structlog.get_logger("lub.orchestration.hooks")


@dataclass
class HookContext:
    """Mutable context threaded through pre- and post-hooks for one call."""

    prompt: str
    result: UncertaintyResult | None = None
    state: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Hook(Protocol):
    """Callable that receives a :class:`HookContext`."""

    def __call__(self, ctx: HookContext) -> None: ...


@dataclass
class PipelineHookRegistry:
    """Ordered collections of pre- and post-hooks for the pipeline lifecycle."""

    pre_answer: list[Hook] = field(default_factory=list)
    post_answer: list[Hook] = field(default_factory=list)

    def add_pre(self, hook: Hook) -> None:
        """Append ``hook`` to the pre-answer chain."""
        self.pre_answer.append(hook)

    def add_post(self, hook: Hook) -> None:
        """Append ``hook`` to the post-answer chain."""
        self.post_answer.append(hook)

    def fire_pre(self, ctx: HookContext) -> None:
        """Run every pre-answer hook in registration order."""
        for h in self.pre_answer:
            _safe_fire(h, ctx, phase="pre")

    def fire_post(self, ctx: HookContext) -> None:
        """Run every post-answer hook in registration order."""
        for h in self.post_answer:
            _safe_fire(h, ctx, phase="post")


# Legacy alias -- kept for backwards-compat.
HookRegistry = PipelineHookRegistry


def _safe_fire(hook: Hook, ctx: HookContext, *, phase: str) -> None:
    try:
        hook(ctx)
    except Exception as exc:  # noqa: BLE001 -- hooks must never break the pipeline.
        _LOG.warning(
            "hooks.error",
            phase=phase,
            hook=getattr(hook, "__name__", type(hook).__name__),
            error=str(exc),
        )


class HookedPipeline:
    """Thin wrapper around a pipeline that fires a :class:`PipelineHookRegistry`.

    Satisfies :class:`~lub.protocols.PipelineProto`, plugs into
    :class:`~lub.guard.UncertaintyGuard` or any other consumer.
    """

    def __init__(self, pipeline: PipelineProto, registry: PipelineHookRegistry) -> None:
        self.pipeline = pipeline
        self.registry = registry

    def answer(self, prompt: str, **kwargs: Any) -> UncertaintyResult:
        """Invoke the wrapped pipeline, firing pre- and post-hooks around it."""
        ctx = HookContext(prompt=prompt)
        self.registry.fire_pre(ctx)
        result = self.pipeline.answer(prompt, **kwargs)
        ctx.result = result
        self.registry.fire_post(ctx)
        return result


# Reference hooks ------------------------------------------------------------


def evidence_knn_prehook(store: Any, k: int = 5) -> Hook:
    """Pre-hook that attaches k-NN neighbours from an evidence store."""

    def _hook(ctx: HookContext) -> None:
        neighbours = store.query(ctx.prompt, k=k)
        ctx.state["evidence.neighbours"] = neighbours
        if neighbours:
            correct_rate = sum(1.0 for n in neighbours if getattr(n, "correct", False))
            ctx.state["evidence.correct_rate"] = correct_rate / len(neighbours)
        else:
            ctx.state["evidence.correct_rate"] = 0.0

    _hook.__name__ = "evidence_knn_prehook"
    return _hook


def ledger_log_posthook(
    ledger: Any,
    *,
    domain: str = "generic",
    model: str = "unknown",
    backend: str = "unknown",
) -> Hook:
    """Post-hook that persists (prompt, answer, uq_scores) to the ledger."""

    def _hook(ctx: HookContext) -> None:
        if ctx.result is None:
            return
        query_id = ledger.log_query(prompt=ctx.prompt, domain=domain)
        answer_id = ledger.log_answer(
            query_id=query_id,
            model=model,
            backend=backend,
            answer=ctx.result.answer,
        )
        for method, value in ctx.result.raw_scores.items():
            ledger.log_score(answer_id=answer_id, method=method, value=float(value))
        ledger.log_score(
            answer_id=answer_id,
            method="confidence",
            value=float(ctx.result.confidence),
        )
        ctx.state["ledger.answer_id"] = answer_id

    _hook.__name__ = "ledger_log_posthook"
    return _hook


# Backwards-compatible type alias for code that takes a raw callable.
HookCallable = Callable[[HookContext], None]


__all__ = [
    "Hook",
    "HookCallable",
    "HookContext",
    "HookRegistry",
    "HookedPipeline",
    "evidence_knn_prehook",
    "ledger_log_posthook",
]
