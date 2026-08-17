# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Azure OpenAI Service wrapper for the Bradesco Bridge platform.

Implements the :class:`LLMBackend` protocol used by
:mod:`lub.agents.chatbot`, :mod:`lub.agents.call_center`, and
:mod:`lub.agents.smart_payments`. Handles authentication, rate limiting
with exponential back-off, automatic retries, and per-request token
tracking.

Requires: ``pip install openai>=1.0``

Usage::

    from lub.connectors.bridge.integrations.azure_openai import AzureOpenAIBackend, AzureOpenAIConfig

    cfg = AzureOpenAIConfig(
        endpoint="https://my-resource.openai.azure.com/",
        api_key="sk-...",
        deployment="gpt-4o",
    )
    backend = AzureOpenAIBackend(cfg)
    answer = backend.complete("What is CET1 capital?")
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, ClassVar

import structlog

from lub.config import LubConfig
from lub.governance.local_only import enforce

_LOG = structlog.get_logger("lub.integrations.azure_openai")

_MISSING_MSG = (
    "The 'openai' package is required for AzureOpenAIBackend. "
    "Install it with: pip install 'openai>=1.0'"
)

try:
    import openai
except ImportError:  # pragma: no cover
    openai = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AzureOpenAIConfig:
    """Configuration for the Azure OpenAI Service connection.

    Attributes:
        endpoint: Azure OpenAI resource endpoint URL.
        api_key: API key for authentication.
        deployment: Name of the deployed model (e.g. ``"gpt-4o"``).
        api_version: Azure OpenAI API version string.
        max_retries: Maximum number of retries on transient failures.
        retry_base_delay: Base delay in seconds for exponential back-off.
        timeout: Request timeout in seconds.
        max_tokens: Default maximum tokens for completions.
        temperature: Default sampling temperature.
    """

    endpoint: str
    api_key: str
    deployment: str
    api_version: str = "2024-10-21"
    max_retries: int = 3
    retry_base_delay: float = 1.0
    timeout: float = 30.0
    max_tokens: int = 1024
    temperature: float = 0.1


# ---------------------------------------------------------------------------
# Token tracker
# ---------------------------------------------------------------------------


@dataclass
class TokenUsage:
    """Cumulative token usage tracker.

    Attributes:
        prompt_tokens: Total prompt tokens consumed.
        completion_tokens: Total completion tokens consumed.
        total_tokens: Total tokens consumed.
        n_requests: Number of successful requests.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    n_requests: int = 0

    def record(self, prompt: int, completion: int) -> None:
        """Record token usage from a single request."""
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion
        self.n_requests += 1

    def to_dict(self) -> dict[str, int]:
        """Serialise to a plain dictionary."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "n_requests": self.n_requests,
        }


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


@dataclass
class AzureOpenAIBackend:
    """Azure OpenAI backend implementing the LLMBackend protocol.

    Provides ``complete()`` for text generation and ``embed()`` for
    embedding extraction. All calls go through rate-limit-aware retry
    logic with exponential back-off.

    Args:
        config: Connection and behaviour configuration.
    """

    # Declares egress to lub.governance.local_only: this class satisfies
    # the LLMBackend protocol without deriving from APIBackend, so the
    # inheritance-based check cannot see it.
    LUB_HOSTED: ClassVar[bool] = True

    config: AzureOpenAIConfig
    usage: TokenUsage = field(default_factory=TokenUsage)
    _client: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        # Checked before the SDK: under the air-gapped profile this
        # backend must be refused whether or not `openai` is installed.
        # It does not derive from APIBackend, so it opts in explicitly —
        # otherwise the profile would have a hole exactly the size of
        # the connector a bank is most likely to reach for.
        enforce(self, local_only=LubConfig().local_only)
        if openai is None:
            raise ImportError(_MISSING_MSG)
        self._client = openai.AzureOpenAI(
            azure_endpoint=self.config.endpoint,
            api_key=self.config.api_key,
            api_version=self.config.api_version,
            timeout=self.config.timeout,
        )
        _LOG.info(
            "azure_openai.init",
            endpoint=self.config.endpoint,
            deployment=self.config.deployment,
            api_version=self.config.api_version,
        )

    def complete(self, prompt: str, **kwargs: Any) -> str:
        """Generate a text completion.

        Sends the prompt as a user message to the configured Azure
        deployment and returns the assistant's reply. Retries on rate
        limit (HTTP 429) and server errors (5xx) with exponential
        back-off.

        Args:
            prompt: The input prompt.
            **kwargs: Additional keyword arguments forwarded to the
                OpenAI ``chat.completions.create`` call.

        Returns:
            The generated text.

        Raises:
            openai.APIError: After all retries are exhausted.
        """
        max_tokens = kwargs.pop("max_tokens", self.config.max_tokens)
        temperature = kwargs.pop("temperature", self.config.temperature)

        messages = [{"role": "user", "content": prompt}]
        last_exc: BaseException | None = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                _LOG.debug(
                    "azure_openai.complete.attempt",
                    attempt=attempt,
                    prompt_len=len(prompt),
                )
                response = self._client.chat.completions.create(
                    model=self.config.deployment,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **kwargs,
                )
                text: str = response.choices[0].message.content or ""

                if response.usage:
                    self.usage.record(
                        prompt=response.usage.prompt_tokens,
                        completion=response.usage.completion_tokens,
                    )
                    _LOG.debug(
                        "azure_openai.complete.tokens",
                        prompt_tokens=response.usage.prompt_tokens,
                        completion_tokens=response.usage.completion_tokens,
                    )

                return text

            except Exception as exc:
                last_exc = exc
                if self._is_retryable(exc) and attempt < self.config.max_retries:
                    delay = self.config.retry_base_delay * (2 ** (attempt - 1))
                    retry_after = self._get_retry_after(exc)
                    if retry_after is not None:
                        delay = max(delay, retry_after)
                    _LOG.warning(
                        "azure_openai.complete.retry",
                        attempt=attempt,
                        delay=f"{delay:.1f}s",
                        error=str(exc),
                    )
                    time.sleep(delay)
                else:
                    _LOG.error(
                        "azure_openai.complete.failed",
                        attempt=attempt,
                        error=str(exc),
                    )
                    raise

        # Should not reach here, but satisfy the type checker.
        raise RuntimeError(  # pragma: no cover
            f"All {self.config.max_retries} retries exhausted."
        ) from last_exc

    def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for the given text.

        Uses the same deployment as completions. For dedicated embedding
        models, create a separate :class:`AzureOpenAIBackend` instance
        with the embedding deployment name.

        Args:
            text: The input text to embed.

        Returns:
            A list of floats representing the embedding vector.

        Raises:
            openai.APIError: After all retries are exhausted.
        """
        last_exc: BaseException | None = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                _LOG.debug(
                    "azure_openai.embed.attempt",
                    attempt=attempt,
                    text_len=len(text),
                )
                response = self._client.embeddings.create(
                    model=self.config.deployment,
                    input=text,
                )
                embedding: list[float] = response.data[0].embedding

                if response.usage:
                    self.usage.record(
                        prompt=response.usage.prompt_tokens,
                        completion=0,
                    )

                return embedding

            except Exception as exc:
                last_exc = exc
                if self._is_retryable(exc) and attempt < self.config.max_retries:
                    delay = self.config.retry_base_delay * (2 ** (attempt - 1))
                    retry_after = self._get_retry_after(exc)
                    if retry_after is not None:
                        delay = max(delay, retry_after)
                    _LOG.warning(
                        "azure_openai.embed.retry",
                        attempt=attempt,
                        delay=f"{delay:.1f}s",
                        error=str(exc),
                    )
                    time.sleep(delay)
                else:
                    _LOG.error(
                        "azure_openai.embed.failed",
                        attempt=attempt,
                        error=str(exc),
                    )
                    raise

        raise RuntimeError(  # pragma: no cover
            f"All {self.config.max_retries} retries exhausted."
        ) from last_exc

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_retryable(exc: BaseException) -> bool:
        """Determine whether an exception is transient and retryable."""
        if openai is None:
            return False  # pragma: no cover
        if isinstance(exc, openai.RateLimitError):
            return True
        if isinstance(exc, openai.APIStatusError) and exc.status_code >= 500:
            return True
        return bool(isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)))

    @staticmethod
    def _get_retry_after(exc: BaseException) -> float | None:
        """Extract Retry-After header value from an API error, if present."""
        headers = getattr(exc, "response", None)
        if headers is not None:
            headers = getattr(headers, "headers", None)
        if headers is not None:
            retry_after = headers.get("Retry-After") or headers.get("retry-after")
            if retry_after is not None:
                try:
                    return float(retry_after)
                except (ValueError, TypeError):
                    pass
        return None


__all__ = ["AzureOpenAIBackend", "AzureOpenAIConfig", "TokenUsage"]
