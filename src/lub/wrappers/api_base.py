# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Shared base class for remote-API backends (OpenAI, Anthropic, ...).

Hosted LLM providers share a lot of boilerplate: lazy SDK import,
API-key lookup via :class:`LubConfig`, tenacity-based retry on a
standard set of transient error class names, and a configurable
request timeout. ``APIBackend`` lifts that boilerplate out of each
concrete wrapper so a new hosted provider costs ~30 lines instead of
~120.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar, TypeVar

import structlog
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from lub.config import LubConfig
from lub.exceptions import EgressViolation
from lub.wrappers.base import ModelBackend

_LOG = structlog.get_logger("lub.wrappers.api_base")

_F = TypeVar("_F", bound=Callable[..., Any])

DEFAULT_RETRYABLE_NAMES: frozenset[str] = frozenset(
    {"RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError"}
)
DEFAULT_HTTP_TIMEOUT_S: float = 60.0
DEFAULT_MAX_ATTEMPTS: int = 3
DEFAULT_RETRY_WAIT_MULTIPLIER: float = 1.0
DEFAULT_RETRY_WAIT_MIN_S: float = 1.0
DEFAULT_RETRY_WAIT_MAX_S: float = 10.0


class APIBackend(ModelBackend):
    """Abstract base for hosted-API backends.

    Subclasses set ``SDK_PACKAGE`` (PyPI import name), ``CONFIG_KEY``
    (attribute on :class:`LubConfig`), ``ENV_VAR`` (human-readable name
    for the error message), and implement :meth:`_build_client`.
    """

    SDK_PACKAGE: ClassVar[str] = ""
    CONFIG_KEY: ClassVar[str] = ""
    ENV_VAR: ClassVar[str] = ""
    RETRYABLE_NAMES: ClassVar[frozenset[str]] = DEFAULT_RETRYABLE_NAMES
    HTTP_TIMEOUT_S: ClassVar[float] = DEFAULT_HTTP_TIMEOUT_S

    # Retry tunables -- subclasses override when their provider has
    # tighter rate limits or longer recovery windows than the
    # conservative defaults below. Tenacity reads these via
    # :meth:`_retry`, which subclasses can also override wholesale if
    # they need a non-exponential schedule.
    MAX_ATTEMPTS: ClassVar[int] = DEFAULT_MAX_ATTEMPTS
    RETRY_WAIT_MULTIPLIER: ClassVar[float] = DEFAULT_RETRY_WAIT_MULTIPLIER
    RETRY_WAIT_MIN_S: ClassVar[float] = DEFAULT_RETRY_WAIT_MIN_S
    RETRY_WAIT_MAX_S: ClassVar[float] = DEFAULT_RETRY_WAIT_MAX_S

    def __init__(self, model_id: str, config: LubConfig | None = None) -> None:
        super().__init__(model_id)
        self._config = config or LubConfig()
        # Fail closed before any prompt exists: under the air-gapped profile a
        # hosted backend must not be constructible at all. Raised inline rather
        # than delegated to lub.governance.local_only because this is a core
        # layer and the import contract forbids it from importing governance —
        # see the note in that module.
        if self._config.local_only:
            _LOG.warning("local_only.refused", backend=type(self).__name__)
            raise EgressViolation(type(self).__name__)
        self._client: Any = None

    @classmethod
    def _load_sdk(cls) -> Any:
        import importlib

        try:
            return importlib.import_module(cls.SDK_PACKAGE)
        except ImportError as exc:
            raise ImportError(
                f"{cls.__name__} requires the {cls.SDK_PACKAGE!r} package. "
                f"Install with: pip install {cls.SDK_PACKAGE}"
            ) from exc

    def _build_client(self, sdk: Any, api_key: str) -> Any:
        """Construct and return the SDK client. Must be overridden."""
        raise NotImplementedError

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        sdk = self._load_sdk()
        api_key = getattr(self._config, self.CONFIG_KEY, None)
        if not api_key:
            raise RuntimeError(
                f"{self.ENV_VAR} API key not configured. Set env var LUB_{self.ENV_VAR}."
            )
        self._client = self._build_client(sdk, api_key)
        return self._client

    @classmethod
    def _is_retryable(cls, exc: BaseException) -> bool:
        return type(exc).__name__ in cls.RETRYABLE_NAMES

    @classmethod
    def _retry(cls) -> Callable[[_F], _F]:
        """Build a retry decorator from the class-level retry tunables.

        Subclasses can either tweak the public class vars
        (:attr:`MAX_ATTEMPTS`, :attr:`RETRY_WAIT_MULTIPLIER`,
        :attr:`RETRY_WAIT_MIN_S`, :attr:`RETRY_WAIT_MAX_S`,
        :attr:`RETRYABLE_NAMES`) for a routine adjustment, or override
        this method entirely for a non-exponential backoff strategy.
        """
        decorator: Callable[[_F], _F] = retry(
            stop=stop_after_attempt(cls.MAX_ATTEMPTS),
            wait=wait_exponential(
                multiplier=cls.RETRY_WAIT_MULTIPLIER,
                min=cls.RETRY_WAIT_MIN_S,
                max=cls.RETRY_WAIT_MAX_S,
            ),
            retry=retry_if_exception(cls._is_retryable),
            reraise=True,
        )
        return decorator


__all__ = ["APIBackend"]
