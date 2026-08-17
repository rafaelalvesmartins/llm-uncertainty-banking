# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Runtime configuration, loaded from env vars with prefix ``LUB_``.

All settings can be supplied either as environment variables
(``LUB_<UPPER_NAME>``) or in a ``.env`` file at the working directory
root. Pydantic-settings handles the precedence: explicit constructor
args > environment variables > .env file > defaults.

Documented environment variables
--------------------------------

==========================  =========================================  =================
Variable                    Purpose                                    Default
==========================  =========================================  =================
``LUB_CACHE_DIR``           Directory for cached HuggingFace models,   ``~/.cache/lub``
                            tokenizers, and downloaded datasets.
``LUB_LOG_LEVEL``           Log level for ``structlog`` emitters       ``"INFO"``
                            (``DEBUG`` / ``INFO`` / ``WARNING`` /
                            ``ERROR``).
``LUB_OPENAI_API_KEY``      API key for the OpenAI backend             ``None`` (must be
                            (:class:`lub.wrappers.openai.OpenAIBackend`).  set if backend is
                                                                       used).
``LUB_ANTHROPIC_API_KEY``   API key for the Anthropic backend.         ``None``
``LUB_REQUEST_TIMEOUT_S``   Per-request timeout in seconds for         ``60.0``
                            hosted-API backends.
``LUB_RETRY_ATTEMPTS``      Default number of retry attempts on        ``3``
                            transient backend errors. ``APIBackend``
                            subclasses can override per-provider via
                            ``MAX_ATTEMPTS`` class var.
``LUB_LOCAL_ONLY``          Air-gapped profile. When true, hosted-API  ``False``
                            backends refuse to construct — see
                            :mod:`lub.governance.local_only` for the
                            exact scope of the guarantee.
==========================  =========================================  =================

Test-suite-only variables (not part of :class:`LubConfig`)
----------------------------------------------------------

==========================  =================================================
Variable                    Purpose
==========================  =================================================
``LUB_REAL_BACKEND_TESTS``  Set to ``1`` to opt in to integration tests
                            marked ``@pytest.mark.real_backend`` (these hit
                            live LLM providers and cost money).
==========================  =================================================
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_cache_dir() -> Path:
    return Path.home() / ".cache" / "lub"


class LubConfig(BaseSettings):
    """Global settings object injected at pipeline construction time.

    All fields are populated from ``LUB_*`` environment variables (see
    module docstring for the full list). The pydantic-settings
    ``env_prefix`` convention turns ``cache_dir`` into
    ``LUB_CACHE_DIR``, ``request_timeout_s`` into
    ``LUB_REQUEST_TIMEOUT_S``, etc.
    """

    model_config = SettingsConfigDict(
        env_prefix="LUB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    cache_dir: Path = Field(default_factory=_default_cache_dir)
    log_level: str = "INFO"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    request_timeout_s: float = 60.0
    retry_attempts: int = 3
    local_only: bool = False

    def ensure_cache_dir(self) -> Path:
        """Create the cache directory if it does not exist and return it."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cache_dir


__all__ = ["LubConfig"]
