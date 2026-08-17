# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for ``lub.connectors.bridge.async_wrapper.AsyncBridgePlatform``."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from lub.connectors.bridge import AgentRole
from lub.connectors.bridge.async_wrapper import AsyncBridgePlatform
from lub.connectors.bridge.platform import BridgePlatform
from lub.guard import PolicyDecision


@pytest.fixture
def sync_platform() -> BridgePlatform:
    guard = MagicMock()
    guard.threshold = 0.5
    guard.abstain_marker = "[ABSTAIN]"
    guard.on_fail = MagicMock(value="abstain")
    fake_result = MagicMock()
    fake_result.answer = "guard answer"
    fake_result.raw.confidence = 0.9
    fake_result.raw.answer = "guard answer"
    fake_result.outcome.decision = PolicyDecision.PASSTHROUGH
    fake_result.outcome.passed = True
    fake_result.outcome.reason = "ok"
    guard.return_value = fake_result

    platform = BridgePlatform(guard=guard)
    platform.register_agent(AgentRole.CHATBOT, lambda p: f"answer: {p}")
    return platform


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_creates_default_executor(self, sync_platform: BridgePlatform) -> None:
        wrapper = AsyncBridgePlatform(platform=sync_platform)
        assert wrapper.executor is not None
        assert wrapper._owns_executor is True
        wrapper.close()

    def test_accepts_custom_executor(self, sync_platform: BridgePlatform) -> None:
        ex = ThreadPoolExecutor(max_workers=2)
        wrapper = AsyncBridgePlatform(platform=sync_platform, executor=ex)
        assert wrapper.executor is ex
        assert wrapper._owns_executor is False
        ex.shutdown(wait=True)


# ---------------------------------------------------------------------------
# Async methods round-trip through the sync platform
# ---------------------------------------------------------------------------


class TestAsyncMethods:
    @pytest.mark.asyncio
    async def test_aquery_returns_answer(self, sync_platform: BridgePlatform) -> None:
        async with AsyncBridgePlatform(platform=sync_platform) as wrapper:
            answer = await wrapper.aquery("PIX info?")
        assert "answer:" in answer

    @pytest.mark.asyncio
    async def test_aquery_with_confidence_returns_bridge_result(
        self, sync_platform: BridgePlatform
    ) -> None:
        async with AsyncBridgePlatform(platform=sync_platform) as wrapper:
            result = await wrapper.aquery_with_confidence("test")
        assert result.primary.answer.startswith("answer:")

    @pytest.mark.asyncio
    async def test_ahealth_check_runs(self, sync_platform: BridgePlatform) -> None:
        async with AsyncBridgePlatform(platform=sync_platform) as wrapper:
            health = await wrapper.ahealth_check()
        # Doesn't raise; returns a PlatformHealth.
        assert hasattr(health, "healthy")


# ---------------------------------------------------------------------------
# Concurrency: the wrapper actually parallelizes
# ---------------------------------------------------------------------------


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_queries_share_event_loop(
        self, sync_platform: BridgePlatform
    ) -> None:
        """Multiple aquery calls should run concurrently in the executor."""
        async with AsyncBridgePlatform(platform=sync_platform) as wrapper:
            start = time.perf_counter()
            results = await asyncio.gather(
                *[wrapper.aquery(f"q{i}") for i in range(5)]
            )
            duration = time.perf_counter() - start
        assert len(results) == 5
        # Each query is fast (mock), so 5 concurrent should be much under
        # 5 * 1s. Just sanity that we don't serialize.
        assert duration < 2.0


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    def test_close_shuts_down_owned_executor(
        self, sync_platform: BridgePlatform
    ) -> None:
        wrapper = AsyncBridgePlatform(platform=sync_platform)
        wrapper.close()
        # No second close should raise.
        wrapper.close()

    def test_close_does_not_shut_down_external_executor(
        self, sync_platform: BridgePlatform
    ) -> None:
        ex = ThreadPoolExecutor(max_workers=1)
        wrapper = AsyncBridgePlatform(platform=sync_platform, executor=ex)
        wrapper.close()
        # External executor still usable.
        future = ex.submit(lambda: 42)
        assert future.result(timeout=1) == 42
        ex.shutdown(wait=True)
