# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Anthropic backend.

Wraps the official ``anthropic`` Python SDK. Unlike the OpenAI SDK, the
Messages API does not support ``n`` or token-level logprobs, so
``generate`` loops for multiple samples and ``logprobs``/``embed`` raise
``NotImplementedError`` with actionable messages.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import structlog

from lub.types import Generation, TokenLogProbs
from lub.wrappers.api_base import APIBackend
from lub.wrappers.base import BackendCapability

_LOG = structlog.get_logger("lub.wrappers.anthropic")


class AnthropicBackend(APIBackend):
    """Anthropic Messages API backend."""

    REGISTRY_KEY = "anthropic"
    CAPABILITIES = BackendCapability.GENERATE
    SDK_PACKAGE = "anthropic"
    CONFIG_KEY = "anthropic_api_key"
    ENV_VAR = "ANTHROPIC_API_KEY"

    def _build_client(self, sdk: Any, api_key: str) -> Any:
        return sdk.Anthropic(api_key=api_key, timeout=self.HTTP_TIMEOUT_S)

    @APIBackend._retry()
    def _message(self, **kwargs: Any) -> Any:
        return self._get_client().messages.create(model=self.model_id, **kwargs)

    def generate(
        self,
        prompt: str,
        n_samples: int = 1,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> list[Generation]:
        """Generate ``n_samples`` completions for ``prompt`` via the Messages API."""
        if n_samples < 1:
            raise ValueError(f"n_samples must be >= 1, got {n_samples}")
        results: list[Generation] = []
        for _ in range(n_samples):
            response = self._message(
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            text_parts: list[str] = []
            for block in response.content:
                text = getattr(block, "text", None)
                if text:
                    text_parts.append(text)
            results.append(
                Generation(
                    text="".join(text_parts),
                    logprobs=[],
                    finish_reason=getattr(response, "stop_reason", "stop") or "stop",
                )
            )
        return results

    def logprobs(self, prompt: str, completion: str) -> TokenLogProbs:
        """Raise ``NotImplementedError`` since Anthropic exposes no token log-probabilities."""
        raise NotImplementedError(
            "Anthropic Messages API does not expose token log-probabilities. "
            "Use HFBackend or OpenAIBackend for estimators that need logprobs, "
            "or switch to a sampling-based estimator such as self_consistency."
        )

    def embed(self, text: str) -> np.ndarray[Any, Any]:
        """Raise ``NotImplementedError`` since Anthropic has no embeddings API."""
        raise NotImplementedError(
            "Anthropic has no embeddings API. Use OpenAIBackend (text-embedding-3-small) "
            "or HFBackend for embedding-based estimators such as semantic_entropy."
        )


__all__ = ["AnthropicBackend"]
