# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Integration-style tests for FailoverChain using DummyBackend pipelines.

The original test_failover_chain.py uses MagicMock for the pipeline and
backend layers, which catches Protocol-level bugs but can't catch
interface drift between TieredRouter, the pipeline, and the actual
DummyBackend. This file exercises the full chain with real pipeline-shaped
objects so a wrapper signature change anywhere in the stack would
fail here even if the unit suite passes.

Hermetic: pipelines produce deterministic output, no network, no
real model weights.
"""

from __future__ import annotations

from typing import Any

import pytest

from lub.orchestration.router import (
    FailoverChain,
    FailoverExhausted,
    Tier,
    TieredRouter,
)
from lub.types import UncertaintyResult


class _DeterministicPipeline:
    """Real PipelineProto-shaped pipeline that returns a fixed UncertaintyResult."""

    def __init__(self, confidence: float, answer_text: str = "ok") -> None:
        self._confidence = confidence
        self._answer_text = answer_text
        self.call_count = 0

    def answer(self, prompt: str, **kwargs: Any) -> UncertaintyResult:
        self.call_count += 1
        return UncertaintyResult(
            answer=self._answer_text,
            confidence=self._confidence,
            raw_scores={"determ": self._confidence},
            samples=None,
            should_refuse=False,
        )


class _ErroringPipeline:
    """Pipeline that always raises a chosen exception."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.call_count = 0

    def answer(self, prompt: str, **kwargs: Any) -> UncertaintyResult:
        self.call_count += 1
        raise self.exc


def _real_router(name: str, threshold: float, pipeline: Any, cost: float = 0.0) -> TieredRouter:
    return TieredRouter(tiers=[Tier(name=name, pipeline=pipeline, threshold=threshold, cost=cost)])


# ---------------------------------------------------------------------------
# End-to-end happy path
# ---------------------------------------------------------------------------


def test_chain_picks_first_router_when_all_healthy() -> None:
    """First router succeeds; second is never invoked."""
    p1 = _DeterministicPipeline(confidence=0.95, answer_text="from-primary")
    p2 = _DeterministicPipeline(confidence=0.99, answer_text="from-secondary")
    primary = _real_router("primary", 0.7, p1)
    secondary = _real_router("secondary", 0.7, p2)

    chain = FailoverChain(routers=[primary, secondary])
    result = chain.answer("test prompt")

    assert result.tier_used == "primary"
    assert result.final.answer == "from-primary"
    assert p1.call_count == 1
    assert p2.call_count == 0


def test_chain_escalates_on_timeout_with_real_pipeline() -> None:
    """A real TimeoutError walks the chain correctly."""
    primary_p = _ErroringPipeline(TimeoutError("connection timed out"))
    secondary_p = _DeterministicPipeline(confidence=0.85, answer_text="recovered")

    primary = _real_router("primary", 0.5, primary_p)
    secondary = _real_router("secondary", 0.5, secondary_p)
    chain = FailoverChain(routers=[primary, secondary])

    result = chain.answer("prompt")

    assert result.tier_used == "secondary"
    assert result.final.answer == "recovered"
    assert primary_p.call_count == 1
    assert secondary_p.call_count == 1


def test_chain_escalates_on_connection_error() -> None:
    primary_p = _ErroringPipeline(ConnectionError("network unreachable"))
    secondary_p = _DeterministicPipeline(confidence=0.9, answer_text="ok")
    primary = _real_router("primary", 0.5, primary_p)
    secondary = _real_router("secondary", 0.5, secondary_p)
    chain = FailoverChain(routers=[primary, secondary])

    result = chain.answer("p")
    assert result.tier_used == "secondary"


def test_chain_does_not_swallow_value_error() -> None:
    """A real ValueError (programmer bug) propagates without failover."""
    primary_p = _ErroringPipeline(ValueError("threshold must be positive"))
    secondary_p = _DeterministicPipeline(confidence=0.9, answer_text="should-never-reach")
    primary = _real_router("primary", 0.5, primary_p)
    secondary = _real_router("secondary", 0.5, secondary_p)
    chain = FailoverChain(routers=[primary, secondary])

    with pytest.raises(ValueError, match="threshold must be positive"):
        chain.answer("p")
    assert primary_p.call_count == 1
    assert secondary_p.call_count == 0


def test_chain_exhausts_through_three_real_pipelines() -> None:
    p1 = _ErroringPipeline(TimeoutError("t1"))
    p2 = _ErroringPipeline(ConnectionError("c2"))
    p3 = _ErroringPipeline(OSError("o3"))
    chain = FailoverChain(
        routers=[
            _real_router("r1", 0.5, p1),
            _real_router("r2", 0.5, p2),
            _real_router("r3", 0.5, p3),
        ]
    )

    with pytest.raises(FailoverExhausted) as exc_info:
        chain.answer("p")

    causes = exc_info.value.causes
    assert len(causes) == 3
    assert isinstance(causes[0], TimeoutError)
    assert isinstance(causes[1], ConnectionError)
    assert isinstance(causes[2], OSError)
    assert all(p.call_count == 1 for p in (p1, p2, p3))


def test_monotonicity_rejects_lax_secondary_real_pipeline() -> None:
    primary = _real_router("primary", 0.8, _DeterministicPipeline(0.95))
    secondary = _real_router("secondary", 0.5, _DeterministicPipeline(0.95))

    with pytest.raises(ValueError, match="calibration-monotonicity"):
        FailoverChain(routers=[primary, secondary])


def test_monotonicity_can_be_disabled_for_intentional_lax_chain() -> None:
    primary = _real_router("primary", 0.8, _DeterministicPipeline(0.95))
    secondary = _real_router("secondary", 0.5, _DeterministicPipeline(0.95))

    chain = FailoverChain(
        routers=[primary, secondary],
        enforce_calibration_monotonicity=False,
    )
    assert len(chain.routers) == 2


def test_batch_walks_chain_per_prompt_with_real_pipeline() -> None:
    """SDK-style RateLimitError detected by name heuristic."""

    class RateLimitError(Exception):
        """Class name matches the heuristic."""
        pass

    primary_p = _ErroringPipeline(RateLimitError("429"))
    secondary_p = _DeterministicPipeline(confidence=0.9, answer_text="ok")
    chain = FailoverChain(
        routers=[
            _real_router("primary", 0.5, primary_p),
            _real_router("secondary", 0.5, secondary_p),
        ]
    )

    results = chain.batch(["q1", "q2", "q3"])

    assert len(results) == 3
    assert all(r.tier_used == "secondary" for r in results)
    assert primary_p.call_count == 3
    assert secondary_p.call_count == 3


def test_total_cost_accumulates_across_failover() -> None:
    """The result is the secondary's RouterResult; secondary cost is what's reported."""
    primary_p = _ErroringPipeline(TimeoutError("t"))
    secondary_p = _DeterministicPipeline(confidence=0.9, answer_text="ok")

    primary_router = _real_router("p", 0.5, primary_p, cost=0.01)
    secondary_router = _real_router("s", 0.5, secondary_p, cost=0.10)

    chain = FailoverChain(routers=[primary_router, secondary_router])
    result = chain.answer("prompt")

    assert result.total_cost == 0.10


def test_single_router_chain_works_end_to_end() -> None:
    p = _DeterministicPipeline(confidence=0.99, answer_text="lone")
    chain = FailoverChain(routers=[_real_router("only", 0.5, p)])
    result = chain.answer("prompt")
    assert result.tier_used == "only"
    assert result.final.answer == "lone"
