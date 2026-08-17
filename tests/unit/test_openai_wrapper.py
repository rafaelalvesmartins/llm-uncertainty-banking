# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Tests for lub.wrappers.openai."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from lub.wrappers.openai import OpenAIBackend

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeChatCompletions:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response


class _FakeEmbeddings:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response


class _FakeClient:
    def __init__(self, chat_response: Any = None, embed_response: Any = None) -> None:
        self.chat = SimpleNamespace(
            completions=_FakeChatCompletions(chat_response),
        )
        self.embeddings = _FakeEmbeddings(embed_response)


def _make_backend(
    *,
    chat_response: Any = None,
    embed_response: Any = None,
) -> tuple[OpenAIBackend, _FakeClient]:
    """Build a backend with ``__init__`` bypassed and the SDK client swapped."""
    backend = OpenAIBackend.__new__(OpenAIBackend)
    backend.model_id = "gpt-test"  # type: ignore[attr-defined]
    client = _FakeClient(chat_response=chat_response, embed_response=embed_response)
    backend._get_client = lambda: client  # type: ignore[attr-defined]
    backend._client = client  # type: ignore[attr-defined]
    return backend, client


def _choice(
    text: str = "ok",
    finish_reason: str = "stop",
    token_logprobs: list[float] | None = None,
) -> SimpleNamespace:
    """Build a single chat-completion choice with optional logprobs."""
    if token_logprobs is None:
        lp = None
    else:
        lp = SimpleNamespace(
            content=[SimpleNamespace(logprob=v) for v in token_logprobs],
        )
    return SimpleNamespace(
        message=SimpleNamespace(content=text),
        finish_reason=finish_reason,
        logprobs=lp,
    )


def _chat_response(*choices: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(choices=list(choices))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def single_choice_response() -> SimpleNamespace:
    return _chat_response(_choice("CET1 is core equity tier 1.", "stop", [-0.1, -0.2]))


@pytest.fixture
def multi_choice_response() -> SimpleNamespace:
    return _chat_response(
        _choice("answer a", "stop", [-0.05]),
        _choice("answer b", "length", [-0.5, -0.7]),
        _choice("answer c", "stop", []),
    )


@pytest.fixture
def embed_response() -> SimpleNamespace:
    return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3, 0.4])])


# ---------------------------------------------------------------------------
# Class-level metadata
# ---------------------------------------------------------------------------


class TestRegistryAttributes:
    def test_registry_key(self) -> None:
        assert OpenAIBackend.REGISTRY_KEY == "openai"

    def test_sdk_metadata(self) -> None:
        assert OpenAIBackend.SDK_PACKAGE == "openai"
        assert OpenAIBackend.CONFIG_KEY == "openai_api_key"
        assert OpenAIBackend.ENV_VAR == "OPENAI_API_KEY"

    def test_capabilities_include_generate_and_embed(self) -> None:
        from lub.wrappers.base import BackendCapability

        caps = OpenAIBackend.CAPABILITIES
        assert caps & BackendCapability.GENERATE
        assert caps & BackendCapability.EMBED


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------


class TestGenerate:
    def test_returns_single_sample(self, single_choice_response: SimpleNamespace) -> None:
        backend, _client = _make_backend(chat_response=single_choice_response)
        results = backend.generate("What is CET1?", n_samples=1)
        assert len(results) == 1
        assert results[0].text == "CET1 is core equity tier 1."
        assert results[0].finish_reason == "stop"
        assert results[0].logprobs == [-0.1, -0.2]

    def test_returns_multiple_samples_in_single_call(
        self, multi_choice_response: SimpleNamespace
    ) -> None:
        backend, client = _make_backend(chat_response=multi_choice_response)
        results = backend.generate("q", n_samples=3, temperature=0.9, max_tokens=64)
        assert len(results) == 3
        assert [r.text for r in results] == ["answer a", "answer b", "answer c"]
        assert [r.finish_reason for r in results] == ["stop", "length", "stop"]
        # OpenAI supports n natively → only one upstream call.
        assert len(client.chat.completions.calls) == 1
        call = client.chat.completions.calls[0]
        assert call["n"] == 3
        assert call["temperature"] == 0.9
        assert call["max_tokens"] == 64
        assert call["model"] == "gpt-test"
        assert call["logprobs"] is True
        assert call["messages"] == [{"role": "user", "content": "q"}]

    def test_uses_default_kwargs(self, single_choice_response: SimpleNamespace) -> None:
        backend, client = _make_backend(chat_response=single_choice_response)
        backend.generate("q")
        call = client.chat.completions.calls[0]
        assert call["n"] == 1
        assert call["temperature"] == 0.7
        assert call["max_tokens"] == 256

    def test_rejects_zero_samples(self, single_choice_response: SimpleNamespace) -> None:
        backend, _client = _make_backend(chat_response=single_choice_response)
        with pytest.raises(ValueError, match="n_samples must be >= 1"):
            backend.generate("q", n_samples=0)

    def test_rejects_negative_samples(
        self, single_choice_response: SimpleNamespace
    ) -> None:
        backend, _client = _make_backend(chat_response=single_choice_response)
        with pytest.raises(ValueError, match="n_samples must be >= 1"):
            backend.generate("q", n_samples=-5)

    def test_none_content_becomes_empty_string(self) -> None:
        response = _chat_response(_choice(text="", finish_reason="stop", token_logprobs=[]))
        # message.content can come back as None from the SDK.
        response.choices[0].message.content = None
        backend, _client = _make_backend(chat_response=response)
        results = backend.generate("q")
        assert results[0].text == ""

    def test_missing_logprobs_yields_empty_scores(self) -> None:
        # logprobs=None on the choice (e.g. provider doesn't return them).
        response = _chat_response(_choice("hi", "stop", token_logprobs=None))
        backend, _client = _make_backend(chat_response=response)
        results = backend.generate("q")
        assert results[0].logprobs == []

    def test_logprobs_content_none_yields_empty_scores(self) -> None:
        # logprobs object present but ``.content`` is None.
        response = _chat_response(_choice("hi", "stop", token_logprobs=None))
        response.choices[0].logprobs = SimpleNamespace(content=None)
        backend, _client = _make_backend(chat_response=response)
        results = backend.generate("q")
        assert results[0].logprobs == []

    def test_empty_logprobs_list_preserved(self) -> None:
        response = _chat_response(_choice("hi", "stop", token_logprobs=[]))
        backend, _client = _make_backend(chat_response=response)
        results = backend.generate("q")
        # Empty list (not None) — semantic_entropy etc. distinguish these.
        assert results[0].logprobs == []
        assert results[0].logprobs is not None

    def test_missing_finish_reason_defaults_to_stop(self) -> None:
        response = _chat_response(_choice("hi", finish_reason="", token_logprobs=[-0.1]))
        backend, _client = _make_backend(chat_response=response)
        results = backend.generate("q")
        assert results[0].finish_reason == "stop"

    def test_logprob_values_cast_to_float(self) -> None:
        # SDK may return numpy scalars; downstream code expects plain floats.
        response = _chat_response(
            _choice("hi", "stop", token_logprobs=[np.float32(-0.25), np.float64(-0.5)])
        )
        backend, _client = _make_backend(chat_response=response)
        results = backend.generate("q")
        assert results[0].logprobs == [-0.25, -0.5]
        assert all(isinstance(v, float) for v in results[0].logprobs)

    def test_empty_prompt_passes_through(
        self, single_choice_response: SimpleNamespace
    ) -> None:
        backend, client = _make_backend(chat_response=single_choice_response)
        backend.generate("")
        call = client.chat.completions.calls[0]
        assert call["messages"][0]["content"] == ""

    def test_propagates_backend_error(self) -> None:
        backend, client = _make_backend(chat_response=None)

        def _boom(**_kwargs: Any) -> Any:
            raise RuntimeError("upstream unavailable")

        client.chat.completions.create = _boom  # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="upstream unavailable"):
            backend.generate("q")


# ---------------------------------------------------------------------------
# logprobs()
# ---------------------------------------------------------------------------


class TestLogprobs:
    def test_raises_not_implemented(self) -> None:
        backend, _client = _make_backend()
        with pytest.raises(NotImplementedError) as excinfo:
            backend.logprobs("prompt", "completion")
        msg = str(excinfo.value)
        # Error should point users to the actionable alternatives.
        assert "Chat Completions" in msg
        assert "HFBackend" in msg
        assert "self_consistency" in msg or "semantic_entropy" in msg


# ---------------------------------------------------------------------------
# embed()
# ---------------------------------------------------------------------------


class TestEmbed:
    def test_returns_float32_array(self, embed_response: SimpleNamespace) -> None:
        backend, _client = _make_backend(embed_response=embed_response)
        vec = backend.embed("hello world")
        assert isinstance(vec, np.ndarray)
        assert vec.dtype == np.float32
        np.testing.assert_array_almost_equal(vec, [0.1, 0.2, 0.3, 0.4])

    def test_uses_embedding_model_constant(
        self, embed_response: SimpleNamespace
    ) -> None:
        backend, client = _make_backend(embed_response=embed_response)
        backend.embed("hello")
        call = client.embeddings.calls[0]
        # Embedding model is intentionally decoupled from chat ``model_id``.
        assert call["model"] == "text-embedding-3-small"
        assert call["input"] == "hello"

    def test_empty_text(self, embed_response: SimpleNamespace) -> None:
        backend, client = _make_backend(embed_response=embed_response)
        vec = backend.embed("")
        assert isinstance(vec, np.ndarray)
        assert vec.dtype == np.float32
        assert client.embeddings.calls[0]["input"] == ""

    def test_propagates_backend_error(self) -> None:
        backend, client = _make_backend()

        def _boom(**_kwargs: Any) -> Any:
            raise TimeoutError("upstream timeout")

        client.embeddings.create = _boom  # type: ignore[assignment]
        with pytest.raises(TimeoutError, match="upstream timeout"):
            backend.embed("anything")
