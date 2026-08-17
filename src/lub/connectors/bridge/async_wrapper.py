# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Async-friendly wrappers around the synchronous Bridge platform.

The core :class:`~lub.connectors.bridge.platform.BridgePlatform` is
synchronous: it predates this module and a full async refactor would
ripple through every collaborator (agents, guard, router, RAG).
For high-QPS deployments (FastAPI app behind uvicorn-workers, or any
asyncio HTTP server), blocking the event loop on each query starves
concurrency.

This module provides :class:`AsyncBridgePlatform`, a thin facade that
runs each platform call inside an executor (default: a ThreadPoolExecutor
sized for I/O-heavy LLM calls). Callers see ``async def query(...)``
methods; the platform itself stays sync.

When to use
-----------
* FastAPI / Starlette routes (async by default) — call .aquery() instead
  of .query().
* gRPC asyncio servers (banking-grade RPC layer).
* Anywhere you'd otherwise wrap with ``run_in_executor`` per-call.

When NOT to use
---------------
* CLI scripts, synchronous Flask, single-threaded tools — the sync
  :class:`BridgePlatform` is simpler and avoids executor overhead.

Performance notes
-----------------
The default executor uses ``max_workers=8`` which fits a typical
LLM-bound workload (each query waits hundreds of ms on a network call,
so 8 in-flight queries saturate ~6 cores of a small instance). Tune via
the ``executor`` parameter if your guard/agent calls are CPU-bound.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass

from lub.connectors.bridge import AgentRole, BridgeResult
from lub.connectors.bridge.platform import BridgePlatform, PlatformHealth

__all__ = ["AsyncBridgePlatform"]


_DEFAULT_MAX_WORKERS = 8


@dataclass
class AsyncBridgePlatform:
    """Async facade over a sync :class:`BridgePlatform`.

    Construct it with an existing :class:`BridgePlatform` (already wired
    with its guard, agents, etc.) and call the ``a*`` methods from
    asyncio code. The wrapper does **not** parallelize a single query's
    pipeline stages — it runs the platform call in an executor so the
    asyncio event loop can serve other queries concurrently.

    Lifetime: when the AsyncBridgePlatform is no longer needed and an
    auto-created executor was used, call :meth:`close` to release the
    threads. If you supplied your own executor, manage its lifetime
    elsewhere.
    """

    platform: BridgePlatform
    executor: Executor | None = None
    """Pool used to run sync platform calls. Default: an internal
    ThreadPoolExecutor with 8 workers."""

    def __post_init__(self) -> None:
        self._owns_executor = self.executor is None
        if self.executor is None:
            self.executor = ThreadPoolExecutor(
                max_workers=_DEFAULT_MAX_WORKERS,
                thread_name_prefix="bridge-async",
            )

    async def aquery(
        self,
        prompt: str,
        role: AgentRole | None = None,
        *,
        customer_id: str | None = None,
    ) -> str:
        """Async equivalent of :meth:`BridgePlatform.query`."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.executor,
            lambda: self.platform.query(prompt, role),
        )

    async def aquery_with_confidence(
        self,
        prompt: str,
        role: AgentRole | None = None,
        *,
        customer_id: str | None = None,
    ) -> BridgeResult:
        """Async equivalent of :meth:`BridgePlatform.query_with_confidence`."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.executor,
            lambda: self.platform.query_with_confidence(prompt, role, customer_id=customer_id),
        )

    async def ahealth_check(self) -> PlatformHealth:
        """Async equivalent of :meth:`BridgePlatform.health_check`."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.executor,
            self.platform.health_check,
        )

    def close(self) -> None:
        """Release the auto-created executor (no-op for caller-supplied)."""
        if self._owns_executor and self.executor is not None:
            self.executor.shutdown(wait=False)

    async def __aenter__(self) -> AsyncBridgePlatform:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self.close()
