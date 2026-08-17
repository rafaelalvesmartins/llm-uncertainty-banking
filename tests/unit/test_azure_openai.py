# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for :mod:`lub.integrations.azure_openai`."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lub.connectors.bridge.integrations import azure_openai as az
from lub.connectors.bridge.integrations.azure_openai import (
    AzureOpenAIBackend,
    AzureOpenAIConfig,
    TokenUsage,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> AzureOpenAIConfig:
    """Minimal config for backend construction."""
    return AzureOpenAIConfig(
        endpoint="https://test.openai.azure.com/",
        api_key="sk-test-key",
        deployment="gpt-4o",
        max_retries=3,
        retry_base_delay=0.0,  # no real sleep during tests
        timeout=5.0,
    )


@pytest.fixture
def fake_completion_response() -> SimpleNamespace:
    """A canned chat.completions response."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content="CET1 is core equity tier 1."))
        ],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8),
    )


@pytest.fixture
def fake_embed_response() -> SimpleNamespace:
    """A canned embeddings response."""
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3, 0.4])],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=0),
    )


@pytest.fixture
def mock_openai_module():
    """Patch the module-level ``openai`` symbol with a MagicMock.

    Provides real exception classes so ``isinstance`` checks in
    ``_is_retryable`` work, and a callable ``AzureOpenAI`` factory.
    """

    class _RateLimitError(Exception):
        pass

    class _APIStatusError(Exception):
        def __init__(self, message: str, status_code: int = 500) -> None:
            super().__init__(message)
            self.status_code = status_code

    class _APIConnectionError(Exception):
        pass

    class _APITimeoutError(Exception):
        pass

    fake = MagicMock()
    fake.RateLimitError = _RateLimitError
    fake.APIStatusError = _APIStatusError
    fake.APIConnectionError = _APIConnectionError
    fake.APITimeoutError = _APITimeoutError

    client = MagicMock()
    fake.AzureOpenAI = MagicMock(return_value=client)

    with patch.object(az, "openai", fake):
        yield fake, client


@pytest.fixture
def backend(config, mock_openai_module) -> AzureOpenAIBackend:
    """A backend built against the mocked openai module."""
    return AzureOpenAIBackend(config)


# ---------------------------------------------------------------------------
# AzureOpenAIConfig
# ---------------------------------------------------------------------------


class TestAzureOpenAIConfig:
    def test_required_fields(self) -> None:
        cfg = AzureOpenAIConfig(
            endpoint="https://x.openai.azure.com/",
            api_key="k",
            deployment="d",
        )
        assert cfg.endpoint == "https://x.openai.azure.com/"
        assert cfg.api_key == "k"
        assert cfg.deployment == "d"

    def test_defaults(self) -> None:
        cfg = AzureOpenAIConfig(endpoint="e", api_key="k", deployment="d")
        assert cfg.api_version == "2024-10-21"
        assert cfg.max_retries == 3
        assert cfg.retry_base_delay == 1.0
        assert cfg.timeout == 30.0
        assert cfg.max_tokens == 1024
        assert 0.0 <= cfg.temperature <= 1.0

    def test_is_frozen(self) -> None:
        cfg = AzureOpenAIConfig(endpoint="e", api_key="k", deployment="d")
        with pytest.raises(Exception):
            cfg.api_key = "rotated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TokenUsage
# ---------------------------------------------------------------------------


class TestTokenUsage:
    def test_initial_state_is_zero(self) -> None:
        u = TokenUsage()
        assert u.prompt_tokens == 0
        assert u.completion_tokens == 0
        assert u.total_tokens == 0
        assert u.n_requests == 0

    def test_record_accumulates(self) -> None:
        u = TokenUsage()
        u.record(prompt=10, completion=5)
        u.record(prompt=4, completion=1)
        assert u.prompt_tokens == 14
        assert u.completion_tokens == 6
        assert u.total_tokens == 20
        assert u.n_requests == 2

    def test_record_zero_is_noop_on_totals(self) -> None:
        u = TokenUsage()
        u.record(prompt=0, completion=0)
        assert u.total_tokens == 0
        assert u.n_requests == 1  # still counts the call

    def test_to_dict_round_trip(self) -> None:
        u = TokenUsage()
        u.record(prompt=7, completion=3)
        d = u.to_dict()
        assert d == {
            "prompt_tokens": 7,
            "completion_tokens": 3,
            "total_tokens": 10,
            "n_requests": 1,
        }
        assert all(isinstance(v, int) for v in d.values())


# ---------------------------------------------------------------------------
# AzureOpenAIBackend — construction
# ---------------------------------------------------------------------------


class TestBackendConstruction:
    def test_init_builds_client_with_config(
        self, config: AzureOpenAIConfig, mock_openai_module
    ) -> None:
        fake, _client = mock_openai_module
        AzureOpenAIBackend(config)
        fake.AzureOpenAI.assert_called_once_with(
            azure_endpoint=config.endpoint,
            api_key=config.api_key,
            api_version=config.api_version,
            timeout=config.timeout,
        )

    def test_init_raises_when_openai_missing(self, config: AzureOpenAIConfig) -> None:
        with patch.object(az, "openai", None):
            with pytest.raises(ImportError, match="openai"):
                AzureOpenAIBackend(config)

    def test_initial_usage_is_empty(self, backend: AzureOpenAIBackend) -> None:
        assert backend.usage.total_tokens == 0
        assert backend.usage.n_requests == 0


# ---------------------------------------------------------------------------
# AzureOpenAIBackend.complete
# ---------------------------------------------------------------------------


class TestComplete:
    def test_returns_assistant_text(
        self,
        backend: AzureOpenAIBackend,
        mock_openai_module,
        fake_completion_response,
    ) -> None:
        _fake, client = mock_openai_module
        client.chat.completions.create.return_value = fake_completion_response

        result = backend.complete("What is CET1 capital?")

        assert result == "CET1 is core equity tier 1."
        client.chat.completions.create.assert_called_once()
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o"
        assert call_kwargs["messages"] == [
            {"role": "user", "content": "What is CET1 capital?"}
        ]

    def test_records_token_usage(
        self,
        backend: AzureOpenAIBackend,
        mock_openai_module,
        fake_completion_response,
    ) -> None:
        _fake, client = mock_openai_module
        client.chat.completions.create.return_value = fake_completion_response

        backend.complete("hi")

        assert backend.usage.prompt_tokens == 12
        assert backend.usage.completion_tokens == 8
        assert backend.usage.total_tokens == 20
        assert backend.usage.n_requests == 1

    def test_empty_prompt_is_passed_through(
        self,
        backend: AzureOpenAIBackend,
        mock_openai_module,
        fake_completion_response,
    ) -> None:
        _fake, client = mock_openai_module
        client.chat.completions.create.return_value = fake_completion_response

        backend.complete("")

        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["messages"][0]["content"] == ""

    def test_kwargs_override_defaults(
        self,
        backend: AzureOpenAIBackend,
        mock_openai_module,
        fake_completion_response,
    ) -> None:
        _fake, client = mock_openai_module
        client.chat.completions.create.return_value = fake_completion_response

        backend.complete("q", max_tokens=42, temperature=0.7)

        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 42
        assert call_kwargs["temperature"] == 0.7

    def test_uses_config_defaults_when_no_kwargs(
        self,
        backend: AzureOpenAIBackend,
        mock_openai_module,
        fake_completion_response,
        config: AzureOpenAIConfig,
    ) -> None:
        _fake, client = mock_openai_module
        client.chat.completions.create.return_value = fake_completion_response

        backend.complete("q")

        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == config.max_tokens
        assert call_kwargs["temperature"] == config.temperature

    def test_none_content_becomes_empty_string(
        self,
        backend: AzureOpenAIBackend,
        mock_openai_module,
    ) -> None:
        _fake, client = mock_openai_module
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=0),
        )
        assert backend.complete("q") == ""

    def test_retries_on_rate_limit_then_succeeds(
        self,
        backend: AzureOpenAIBackend,
        mock_openai_module,
        fake_completion_response,
    ) -> None:
        fake, client = mock_openai_module
        client.chat.completions.create.side_effect = [
            fake.RateLimitError("429"),
            fake_completion_response,
        ]
        with patch.object(az.time, "sleep") as mock_sleep:
            result = backend.complete("q")
        assert result == "CET1 is core equity tier 1."
        assert client.chat.completions.create.call_count == 2
        mock_sleep.assert_called_once()

    def test_retries_on_5xx_then_succeeds(
        self,
        backend: AzureOpenAIBackend,
        mock_openai_module,
        fake_completion_response,
    ) -> None:
        fake, client = mock_openai_module
        client.chat.completions.create.side_effect = [
            fake.APIStatusError("500 boom", status_code=500),
            fake_completion_response,
        ]
        with patch.object(az.time, "sleep"):
            result = backend.complete("q")
        assert result.startswith("CET1")
        assert client.chat.completions.create.call_count == 2

    def test_does_not_retry_on_4xx_other_than_429(
        self,
        backend: AzureOpenAIBackend,
        mock_openai_module,
    ) -> None:
        fake, client = mock_openai_module
        client.chat.completions.create.side_effect = fake.APIStatusError(
            "400 bad request", status_code=400
        )
        with pytest.raises(fake.APIStatusError):
            backend.complete("q")
        assert client.chat.completions.create.call_count == 1

    def test_raises_after_exhausting_retries(
        self,
        backend: AzureOpenAIBackend,
        mock_openai_module,
    ) -> None:
        fake, client = mock_openai_module
        client.chat.completions.create.side_effect = fake.RateLimitError("429")
        with patch.object(az.time, "sleep"):
            with pytest.raises(fake.RateLimitError):
                backend.complete("q")
        assert client.chat.completions.create.call_count == backend.config.max_retries

    def test_retry_after_header_overrides_backoff(
        self,
        backend: AzureOpenAIBackend,
        mock_openai_module,
        fake_completion_response,
    ) -> None:
        fake, client = mock_openai_module
        err = fake.RateLimitError("429")
        err.response = SimpleNamespace(headers={"Retry-After": "5"})
        client.chat.completions.create.side_effect = [err, fake_completion_response]
        with patch.object(az.time, "sleep") as mock_sleep:
            backend.complete("q")
        # First (and only) sleep call should honour Retry-After == 5s.
        assert mock_sleep.call_args.args[0] >= 5.0


# ---------------------------------------------------------------------------
# AzureOpenAIBackend.embed
# ---------------------------------------------------------------------------


class TestEmbed:
    def test_returns_embedding_vector(
        self,
        backend: AzureOpenAIBackend,
        mock_openai_module,
        fake_embed_response,
    ) -> None:
        _fake, client = mock_openai_module
        client.embeddings.create.return_value = fake_embed_response

        vec = backend.embed("hello world")

        assert vec == [0.1, 0.2, 0.3, 0.4]
        client.embeddings.create.assert_called_once_with(
            model="gpt-4o", input="hello world"
        )

    def test_records_prompt_tokens_only(
        self,
        backend: AzureOpenAIBackend,
        mock_openai_module,
        fake_embed_response,
    ) -> None:
        _fake, client = mock_openai_module
        client.embeddings.create.return_value = fake_embed_response

        backend.embed("text")

        assert backend.usage.prompt_tokens == 5
        assert backend.usage.completion_tokens == 0
        assert backend.usage.n_requests == 1

    def test_empty_text(
        self,
        backend: AzureOpenAIBackend,
        mock_openai_module,
        fake_embed_response,
    ) -> None:
        _fake, client = mock_openai_module
        client.embeddings.create.return_value = fake_embed_response
        vec = backend.embed("")
        assert isinstance(vec, list)
        assert all(isinstance(x, float) for x in vec)

    def test_retries_on_transient_error(
        self,
        backend: AzureOpenAIBackend,
        mock_openai_module,
        fake_embed_response,
    ) -> None:
        fake, client = mock_openai_module
        client.embeddings.create.side_effect = [
            fake.APIConnectionError("conn reset"),
            fake_embed_response,
        ]
        with patch.object(az.time, "sleep"):
            vec = backend.embed("x")
        assert len(vec) == 4
        assert client.embeddings.create.call_count == 2

    def test_raises_after_exhausting_retries(
        self,
        backend: AzureOpenAIBackend,
        mock_openai_module,
    ) -> None:
        fake, client = mock_openai_module
        client.embeddings.create.side_effect = fake.APITimeoutError("timeout")
        with patch.object(az.time, "sleep"):
            with pytest.raises(fake.APITimeoutError):
                backend.embed("x")
        assert client.embeddings.create.call_count == backend.config.max_retries


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


class TestIsRetryable:
    def test_rate_limit_is_retryable(self, mock_openai_module) -> None:
        fake, _ = mock_openai_module
        assert AzureOpenAIBackend._is_retryable(fake.RateLimitError("429")) is True

    def test_5xx_is_retryable(self, mock_openai_module) -> None:
        fake, _ = mock_openai_module
        assert (
            AzureOpenAIBackend._is_retryable(
                fake.APIStatusError("500", status_code=500)
            )
            is True
        )
        assert (
            AzureOpenAIBackend._is_retryable(
                fake.APIStatusError("503", status_code=503)
            )
            is True
        )

    def test_4xx_is_not_retryable(self, mock_openai_module) -> None:
        fake, _ = mock_openai_module
        assert (
            AzureOpenAIBackend._is_retryable(
                fake.APIStatusError("400", status_code=400)
            )
            is False
        )

    def test_connection_and_timeout_are_retryable(self, mock_openai_module) -> None:
        fake, _ = mock_openai_module
        assert AzureOpenAIBackend._is_retryable(fake.APIConnectionError("x")) is True
        assert AzureOpenAIBackend._is_retryable(fake.APITimeoutError("x")) is True

    def test_arbitrary_exception_is_not_retryable(self, mock_openai_module) -> None:
        assert AzureOpenAIBackend._is_retryable(ValueError("nope")) is False


class TestGetRetryAfter:
    def test_returns_none_when_no_response(self) -> None:
        assert AzureOpenAIBackend._get_retry_after(ValueError("x")) is None

    def test_returns_none_when_no_headers(self) -> None:
        exc = RuntimeError("x")
        exc.response = SimpleNamespace()  # type: ignore[attr-defined]
        assert AzureOpenAIBackend._get_retry_after(exc) is None

    def test_parses_retry_after_seconds(self) -> None:
        exc = RuntimeError("x")
        exc.response = SimpleNamespace(headers={"Retry-After": "3"})  # type: ignore[attr-defined]
        assert AzureOpenAIBackend._get_retry_after(exc) == 3.0

    def test_parses_lowercase_header(self) -> None:
        exc = RuntimeError("x")
        exc.response = SimpleNamespace(headers={"retry-after": "2.5"})  # type: ignore[attr-defined]
        assert AzureOpenAIBackend._get_retry_after(exc) == 2.5

    def test_invalid_value_returns_none(self) -> None:
        exc = RuntimeError("x")
        exc.response = SimpleNamespace(headers={"Retry-After": "soon"})  # type: ignore[attr-defined]
        assert AzureOpenAIBackend._get_retry_after(exc) is None


# ---------------------------------------------------------------------------
# Module-level public API
# ---------------------------------------------------------------------------


def test_all_exports_match_public_symbols() -> None:
    assert set(az.__all__) == {"AzureOpenAIBackend", "AzureOpenAIConfig", "TokenUsage"}
    for name in az.__all__:
        assert hasattr(az, name)
