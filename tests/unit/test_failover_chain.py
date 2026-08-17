# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for lub.orchestration.router.FailoverChain.

Hermetic. Uses fake routers (no network, no real backend). Covers:
- happy path (first router succeeds)
- first transient error -> second succeeds
- all transient errors -> FailoverExhausted with .causes preserved
- non-transient error -> propagates without failover
- calibration-monotonicity validation
- batch dispatch
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from lub.orchestration.router import (
    FailoverChain,
    FailoverExhausted,
    RouterResult,
    Tier,
    TieredRouter,
    _is_transient_backend_error,
)
from lub.types import UncertaintyResult


def _fake_pipeline(confidence: float = 0.9, answer: str = "ok") -> Any:
    """Build a minimum pipeline duck-type with .answer(prompt, **kwargs)."""
    pipe = MagicMock()
    pipe.answer.return_value = UncertaintyResult(
        answer=answer,
        confidence=confidence,
        raw_scores={},
        samples=None,
        should_refuse=False,
    )
    return pipe


def _make_router(name: str = "r", threshold: float = 0.7, confidence: float = 0.9) -> TieredRouter:
    """Single-tier router that always succeeds with the given confidence."""
    return TieredRouter(
        tiers=[Tier(name=name, pipeline=_fake_pipeline(confidence=confidence), threshold=threshold)]
    )


def _erroring_router(exc: BaseException) -> TieredRouter:
    """Router whose tier pipeline raises ``exc`` on every call."""
    pipe = MagicMock()
    pipe.answer.side_effect = exc
    return TieredRouter(tiers=[Tier(name="err", pipeline=pipe, threshold=0.5)])


# ---------------------------------------------------------------------------
# _is_transient_backend_error helper
# ---------------------------------------------------------------------------


def test_transient_detector_stdlib() -> None:
    assert _is_transient_backend_error(TimeoutError("slow"))
    assert _is_transient_backend_error(ConnectionError("reset"))
    assert _is_transient_backend_error(OSError("network"))


def test_transient_detector_sdk_class_names() -> None:
    """SDK-specific exceptions matched by class-name heuristic."""

    class RateLimitError(Exception): ...

    class APIStatusError(Exception): ...

    class TooManyRequests(Exception): ...

    class TransportError(Exception): ...

    for exc_cls in (RateLimitError, APIStatusError, TooManyRequests, TransportError):
        assert _is_transient_backend_error(exc_cls("x")), exc_cls.__name__


def test_transient_detector_rejects_programmer_errors() -> None:
    assert not _is_transient_backend_error(ValueError("bug"))
    assert not _is_transient_backend_error(TypeError("bug"))
    assert not _is_transient_backend_error(KeyError("bug"))
    assert not _is_transient_backend_error(AssertionError("bug"))


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_init_rejects_empty_chain() -> None:
    with pytest.raises(ValueError, match="at least one router"):
        FailoverChain(routers=[])


def test_init_single_router_ok() -> None:
    r = _make_router()
    chain = FailoverChain(routers=[r])
    assert chain.routers == [r]


def test_init_calibration_monotonicity_enforced_by_default() -> None:
    primary = _make_router(threshold=0.8)
    secondary_lax = _make_router(threshold=0.5)  # less strict than primary -- should error
    with pytest.raises(ValueError, match="calibration-monotonicity"):
        FailoverChain(routers=[primary, secondary_lax])


def test_init_calibration_monotonicity_can_be_disabled() -> None:
    primary = _make_router(threshold=0.8)
    secondary_lax = _make_router(threshold=0.5)
    chain = FailoverChain(
        routers=[primary, secondary_lax],
        enforce_calibration_monotonicity=False,
    )
    assert len(chain.routers) == 2


def test_init_equal_thresholds_pass_monotonicity() -> None:
    primary = _make_router(name="a", threshold=0.7)
    secondary = _make_router(name="b", threshold=0.7)
    chain = FailoverChain(routers=[primary, secondary])
    assert len(chain.routers) == 2


def test_init_stricter_secondary_passes_monotonicity() -> None:
    primary = _make_router(name="a", threshold=0.6)
    secondary = _make_router(name="b", threshold=0.9)  # stricter is fine
    chain = FailoverChain(routers=[primary, secondary])
    assert len(chain.routers) == 2


# ---------------------------------------------------------------------------
# answer() dispatch
# ---------------------------------------------------------------------------


def test_answer_happy_path_first_router_wins() -> None:
    primary = _make_router(name="primary", threshold=0.7, confidence=0.95)
    secondary = _make_router(name="secondary", threshold=0.7, confidence=0.99)
    chain = FailoverChain(routers=[primary, secondary])

    result = chain.answer("test")

    assert isinstance(result, RouterResult)
    assert result.tier_used == "primary"
    secondary.tiers[0].pipeline.answer.assert_not_called()


def test_answer_failover_on_timeout() -> None:
    primary = _erroring_router(TimeoutError("timed out"))
    secondary = _make_router(name="secondary", threshold=0.5, confidence=0.9)
    chain = FailoverChain(routers=[primary, secondary])

    result = chain.answer("test")

    assert result.tier_used == "secondary"


def test_answer_failover_on_rate_limit() -> None:
    class RateLimitError(Exception): ...

    primary = _erroring_router(RateLimitError("429"))
    secondary = _make_router(name="secondary", threshold=0.5, confidence=0.9)
    chain = FailoverChain(routers=[primary, secondary])

    result = chain.answer("test")

    assert result.tier_used == "secondary"


def test_answer_all_transient_raises_failover_exhausted() -> None:
    primary = _erroring_router(TimeoutError("primary"))
    secondary = _erroring_router(ConnectionError("secondary"))
    tertiary = _erroring_router(OSError("tertiary"))
    chain = FailoverChain(routers=[primary, secondary, tertiary])

    with pytest.raises(FailoverExhausted) as exc_info:
        chain.answer("test")

    assert len(exc_info.value.causes) == 3
    assert isinstance(exc_info.value.causes[0], TimeoutError)
    assert isinstance(exc_info.value.causes[1], ConnectionError)
    assert isinstance(exc_info.value.causes[2], OSError)


def test_answer_non_transient_propagates_without_failover() -> None:
    primary = _erroring_router(ValueError("config bug"))
    secondary = _make_router(name="secondary", threshold=0.5, confidence=0.9)
    chain = FailoverChain(routers=[primary, secondary])

    with pytest.raises(ValueError, match="config bug"):
        chain.answer("test")

    secondary.tiers[0].pipeline.answer.assert_not_called()


def test_answer_calibration_layer_assert_propagates() -> None:
    """Calibration AssertionError must NOT trigger failover (would mask bugs)."""
    primary = _erroring_router(AssertionError("calibration invariant violated"))
    secondary = _make_router(name="secondary", threshold=0.5, confidence=0.9)
    chain = FailoverChain(routers=[primary, secondary])

    with pytest.raises(AssertionError):
        chain.answer("test")


def test_answer_single_router_no_chain() -> None:
    only = _make_router(name="only", threshold=0.5, confidence=0.95)
    chain = FailoverChain(routers=[only])
    result = chain.answer("test")
    assert result.tier_used == "only"


def test_failover_exhausted_message_lists_error_types() -> None:
    primary = _erroring_router(TimeoutError("a"))
    secondary = _erroring_router(ConnectionError("b"))
    chain = FailoverChain(routers=[primary, secondary])
    with pytest.raises(FailoverExhausted) as exc_info:
        chain.answer("test")
    msg = str(exc_info.value)
    assert "TimeoutError" in msg
    assert "ConnectionError" in msg
    assert "2 router(s)" in msg


# ---------------------------------------------------------------------------
# batch() dispatch
# ---------------------------------------------------------------------------


def test_batch_each_prompt_walks_chain_independently() -> None:
    primary = _erroring_router(TimeoutError("transient"))
    secondary = _make_router(name="secondary", threshold=0.5, confidence=0.9)
    chain = FailoverChain(routers=[primary, secondary])

    results = chain.batch(["q1", "q2", "q3"])

    assert len(results) == 3
    assert all(r.tier_used == "secondary" for r in results)


def test_batch_one_failed_prompt_does_not_break_others() -> None:
    """A non-transient error on one prompt propagates; transient + recovery on others is fine."""

    primary_pipe = MagicMock()
    # First call raises ValueError, subsequent calls succeed
    success_result = UncertaintyResult(
        answer="ok",
        confidence=0.9,
        raw_scores={},
        samples=None,
        should_refuse=False,
    )
    primary_pipe.answer.side_effect = [
        ValueError("bug on first prompt"),
        success_result,
    ]
    primary = TieredRouter(
        tiers=[Tier(name="primary", pipeline=primary_pipe, threshold=0.5)]
    )
    chain = FailoverChain(routers=[primary])

    with pytest.raises(ValueError):
        chain.batch(["bad", "good"])
