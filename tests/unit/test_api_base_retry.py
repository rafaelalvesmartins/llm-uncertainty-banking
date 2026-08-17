# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the per-subclass retry tunables on APIBackend.

Pinned by P3.1: subclasses can adjust ``MAX_ATTEMPTS``,
``RETRY_WAIT_MULTIPLIER``, ``RETRY_WAIT_MIN_S``, ``RETRY_WAIT_MAX_S``,
and ``RETRYABLE_NAMES`` without overriding ``_retry`` itself. These
tests pin the contract so a future refactor that re-hard-codes the
literals fails fast.
"""

from __future__ import annotations

import pytest

from lub.wrappers.api_base import (
    DEFAULT_HTTP_TIMEOUT_S,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_RETRY_WAIT_MAX_S,
    DEFAULT_RETRY_WAIT_MIN_S,
    DEFAULT_RETRY_WAIT_MULTIPLIER,
    DEFAULT_RETRYABLE_NAMES,
    APIBackend,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_defaults_match_class_vars() -> None:
    """Module-level DEFAULT_* should equal the class-level ClassVars."""
    assert APIBackend.MAX_ATTEMPTS == DEFAULT_MAX_ATTEMPTS == 3
    assert APIBackend.RETRY_WAIT_MULTIPLIER == DEFAULT_RETRY_WAIT_MULTIPLIER == 1.0
    assert APIBackend.RETRY_WAIT_MIN_S == DEFAULT_RETRY_WAIT_MIN_S == 1.0
    assert APIBackend.RETRY_WAIT_MAX_S == DEFAULT_RETRY_WAIT_MAX_S == 10.0
    assert APIBackend.HTTP_TIMEOUT_S == DEFAULT_HTTP_TIMEOUT_S == 60.0
    assert APIBackend.RETRYABLE_NAMES == DEFAULT_RETRYABLE_NAMES


# ---------------------------------------------------------------------------
# Retry decorator construction respects subclass overrides
# ---------------------------------------------------------------------------


class _AggressiveRetry(APIBackend):
    """Subclass that demands tighter retries (e.g. provider with strict rate limits)."""

    SDK_PACKAGE = "test_sdk"
    CONFIG_KEY = "test_api_key"
    ENV_VAR = "TEST_API_KEY"
    MAX_ATTEMPTS = 5
    RETRY_WAIT_MIN_S = 0.5
    RETRY_WAIT_MAX_S = 30.0
    RETRY_WAIT_MULTIPLIER = 2.0


def test_subclass_overrides_visible_on_class() -> None:
    """Subclass attribute lookups return the override, not the parent value."""
    assert _AggressiveRetry.MAX_ATTEMPTS == 5
    assert _AggressiveRetry.RETRY_WAIT_MIN_S == 0.5
    assert _AggressiveRetry.RETRY_WAIT_MAX_S == 30.0
    assert _AggressiveRetry.RETRY_WAIT_MULTIPLIER == 2.0
    # Parent unchanged.
    assert APIBackend.MAX_ATTEMPTS == DEFAULT_MAX_ATTEMPTS


def test_retry_decorator_uses_subclass_attempts() -> None:
    """tenacity's ``stop`` should reflect the subclass's MAX_ATTEMPTS."""
    decorator = _AggressiveRetry._retry()
    calls: list[int] = []

    @decorator
    def always_retryable() -> None:
        calls.append(1)
        # RateLimitError is in DEFAULT_RETRYABLE_NAMES via type name match.
        raise type("RateLimitError", (Exception,), {})("rate limited")

    with pytest.raises(Exception, match="rate limited"):
        always_retryable()

    # MAX_ATTEMPTS = 5 -> the wrapped fn was tried 5 times before reraise.
    assert len(calls) == _AggressiveRetry.MAX_ATTEMPTS == 5


def test_retry_decorator_does_not_retry_non_retryable() -> None:
    """Errors not in RETRYABLE_NAMES propagate after a single attempt."""
    decorator = APIBackend._retry()
    calls: list[int] = []

    @decorator
    def value_error_only() -> None:
        calls.append(1)
        raise ValueError("not transient")

    with pytest.raises(ValueError):
        value_error_only()

    assert calls == [1]


def test_retry_decorator_classifies_by_type_name() -> None:
    """``_is_retryable`` matches by class name, not isinstance.

    Important because providers (openai, anthropic) define their own
    error classes that are NOT subclasses of stdlib types but share
    canonical names ('RateLimitError', etc).
    """

    class APITimeoutError(Exception):  # name matches DEFAULT_RETRYABLE_NAMES
        pass

    assert APIBackend._is_retryable(APITimeoutError("hi")) is True

    class SomethingElse(Exception):
        pass

    assert APIBackend._is_retryable(SomethingElse("hi")) is False


# ---------------------------------------------------------------------------
# Subclasses can also tweak RETRYABLE_NAMES
# ---------------------------------------------------------------------------


class _CustomRetryable(APIBackend):
    SDK_PACKAGE = "x"
    CONFIG_KEY = "y"
    ENV_VAR = "Z"
    RETRYABLE_NAMES = frozenset({"MyTransientError"})


def test_subclass_can_replace_retryable_names() -> None:
    class MyTransientError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    assert _CustomRetryable._is_retryable(MyTransientError("x")) is True
    # Was retryable on parent; subclass narrowed the set, so this is False now.
    assert _CustomRetryable._is_retryable(APITimeoutError("x")) is False
    # Parent is unchanged.
    assert APIBackend._is_retryable(APITimeoutError("x")) is True
