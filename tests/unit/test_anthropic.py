# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Tests for lub.wrappers.anthropic."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from lub.wrappers.anthropic import AnthropicBackend


class _FakeMessages:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response


class _FakeClient:
    def __init__(self, response: Any) -> None:
        self.messages = _FakeMessages(response)


def _make_backend(response: Any) -> AnthropicBackend:
    backend = AnthropicBackend.__new__(AnthropicBackend)
    backend.model_id = "claude-test"
    client = _FakeClient(response)
    backend._get_client = lambda: client  # type: ignore[attr-defined]
    backend._client = client  # type: ignore[attr-defined]
    return backend


def _response(text: str = "hello", stop: str = "end_turn") -> Any:
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        stop_reason=stop,
    )


def test_generate_returns_single_sample() -> None:
    backend = _make_backend(_response("hi there"))
    results = backend.generate("prompt", n_samples=1)
    assert len(results) == 1
    assert results[0].text == "hi there"
    assert results[0].finish_reason == "end_turn"
    assert results[0].logprobs == []


def test_generate_loops_for_multiple_samples() -> None:
    backend = _make_backend(_response("x"))
    results = backend.generate("prompt", n_samples=3, temperature=0.5, max_tokens=10)
    assert len(results) == 3
    assert all(r.text == "x" for r in results)


def test_generate_rejects_zero_samples() -> None:
    backend = _make_backend(_response())
    with pytest.raises(ValueError, match="n_samples must be >= 1"):
        backend.generate("prompt", n_samples=0)


def test_generate_concatenates_text_blocks() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(text="foo"),
            SimpleNamespace(text=None),
            SimpleNamespace(text="bar"),
        ],
        stop_reason="stop",
    )
    backend = _make_backend(response)
    results = backend.generate("prompt")
    assert results[0].text == "foobar"


def test_logprobs_raises_not_implemented() -> None:
    backend = _make_backend(_response())
    with pytest.raises(NotImplementedError, match="log-probabilities"):
        backend.logprobs("prompt", "completion")


def test_embed_raises_not_implemented() -> None:
    backend = _make_backend(_response())
    with pytest.raises(NotImplementedError, match="embeddings"):
        backend.embed("text")
