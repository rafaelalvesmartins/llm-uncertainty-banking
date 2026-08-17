# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Contract tests for the shared remote-API backend base class.

Covers the abstract :class:`APIBackend` without talking to any real
SDK. A minimal subclass + a fake SDK module are wired in via a
monkeypatched import so the retry harness, config lookup, and
NotImplementedError guard can all be exercised hermetically.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from lub.config import LubConfig
from lub.wrappers.api_base import (
    DEFAULT_HTTP_TIMEOUT_S,
    DEFAULT_RETRYABLE_NAMES,
    APIBackend,
)


class _FakeSDK:
    """Minimal stand-in for an OpenAI-/Anthropic-style SDK module."""

    def __init__(self) -> None:
        self.created_clients: list[tuple[str, dict[str, Any]]] = []

    def Client(self, api_key: str, **kwargs: Any) -> dict[str, Any]:  # noqa: N802
        self.created_clients.append((api_key, dict(kwargs)))
        return {"api_key": api_key, **kwargs}


class _FakeBackend(APIBackend):
    SDK_PACKAGE = "_lub_fake_sdk"
    CONFIG_KEY = "openai_api_key"
    ENV_VAR = "OPENAI_API_KEY"

    def _build_client(self, sdk: Any, api_key: str) -> Any:
        return sdk.Client(api_key=api_key, timeout=self.HTTP_TIMEOUT_S)

    def generate(self, prompt, n_samples=1, temperature=0.7, max_tokens=256):
        return []  # unused; tests don't exercise generation path

    def logprobs(self, prompt, completion):
        raise NotImplementedError

    def embed(self, text):
        raise NotImplementedError


@pytest.fixture
def fake_sdk(monkeypatch):
    """Install a fake ``_lub_fake_sdk`` module for importlib to find."""
    mod = types.ModuleType("_lub_fake_sdk")
    fake = _FakeSDK()
    mod.Client = fake.Client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "_lub_fake_sdk", mod)
    return fake


def test_defaults_are_populated() -> None:
    assert DEFAULT_HTTP_TIMEOUT_S == 60.0
    assert "RateLimitError" in DEFAULT_RETRYABLE_NAMES
    assert "APITimeoutError" in DEFAULT_RETRYABLE_NAMES


def test_get_client_raises_when_api_key_missing(fake_sdk) -> None:
    # SDK is installed (via fixture), but the API key is missing —
    # we should hit the RuntimeError guard, not the ImportError guard.
    config = LubConfig(openai_api_key=None, _env_file=None)  # type: ignore[call-arg]
    backend = _FakeBackend(model_id="fake-1", config=config)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        backend._get_client()


def test_get_client_builds_once_and_caches(fake_sdk) -> None:
    config = LubConfig(openai_api_key="sk-test", _env_file=None)  # type: ignore[call-arg]
    backend = _FakeBackend(model_id="fake-1", config=config)
    a = backend._get_client()
    b = backend._get_client()
    assert a is b
    assert a["api_key"] == "sk-test"
    assert a["timeout"] == 60.0


def test_load_sdk_raises_import_error_on_missing_package() -> None:
    class _MissingBackend(APIBackend):
        SDK_PACKAGE = "_definitely_not_installed_xyz"
        CONFIG_KEY = "openai_api_key"
        ENV_VAR = "OPENAI_API_KEY"

        def _build_client(self, sdk, api_key):
            return None

        def generate(self, *a, **kw):
            return []

        def logprobs(self, *a, **kw):
            raise NotImplementedError

        def embed(self, *a, **kw):
            raise NotImplementedError

    backend = _MissingBackend(
        model_id="x", config=LubConfig(openai_api_key="sk-x", _env_file=None)  # type: ignore[call-arg]
    )
    with pytest.raises(ImportError, match="_definitely_not_installed_xyz"):
        backend._get_client()


def test_base_class_build_client_is_not_implemented() -> None:
    config = LubConfig(openai_api_key="sk-test", _env_file=None)  # type: ignore[call-arg]

    class _UnoverriddenBackend(APIBackend):
        SDK_PACKAGE = "_lub_fake_sdk"
        CONFIG_KEY = "openai_api_key"
        ENV_VAR = "OPENAI_API_KEY"

        def generate(self, *a, **kw):
            return []

        def logprobs(self, *a, **kw):
            raise NotImplementedError

        def embed(self, *a, **kw):
            raise NotImplementedError

    mod = types.ModuleType("_lub_fake_sdk")
    sys.modules["_lub_fake_sdk"] = mod
    try:
        backend = _UnoverriddenBackend(model_id="x", config=config)
        with pytest.raises(NotImplementedError):
            backend._get_client()
    finally:
        del sys.modules["_lub_fake_sdk"]


def test_is_retryable_matches_by_class_name() -> None:
    class _FakeRateLimit(Exception):
        pass

    _FakeRateLimit.__name__ = "RateLimitError"
    assert APIBackend._is_retryable(_FakeRateLimit("slow down"))
    assert not APIBackend._is_retryable(ValueError("not retryable"))


def test_retry_decorator_retries_and_reraises() -> None:
    class _FakeRateLimit(Exception):
        pass

    _FakeRateLimit.__name__ = "RateLimitError"
    attempts = {"n": 0}

    @_FakeBackend._retry()
    def always_raises() -> None:
        attempts["n"] += 1
        raise _FakeRateLimit("temporary")

    with pytest.raises(_FakeRateLimit):
        always_raises()
    assert attempts["n"] == 3  # stop_after_attempt(3)


def test_retry_does_not_retry_on_non_retryable() -> None:
    attempts = {"n": 0}

    @_FakeBackend._retry()
    def raises_value_error() -> None:
        attempts["n"] += 1
        raise ValueError("hard failure")

    with pytest.raises(ValueError):
        raises_value_error()
    assert attempts["n"] == 1  # no retry on non-retryable
