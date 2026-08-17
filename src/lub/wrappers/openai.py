# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""OpenAI backend.

Wraps the official ``openai`` Python SDK. The SDK is imported lazily via
:class:`APIBackend` so that importing this module does not require
``openai`` to be installed. Rate-limit errors are retried with
exponential backoff via tenacity.

``logprobs`` is intentionally unsupported: the Chat Completions API returns
logprobs only for *newly generated* tokens, not for a user-supplied completion
prefill, so there is no honest way to score ``(prompt, completion)`` pairs
through this SDK. Callers that need per-token logprobs should use
:class:`~lub.wrappers.hf.HFBackend` or switch to a sampling-based estimator.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np
import structlog

from lub.types import Generation, TokenLogProbs
from lub.wrappers.api_base import APIBackend
from lub.wrappers.base import BackendCapability

_LOG = structlog.get_logger("lub.wrappers.openai")

_EMBEDDING_MODEL = "text-embedding-3-small"


class OpenAIBackend(APIBackend):
    """OpenAI chat + embeddings backend."""

    REGISTRY_KEY = "openai"
    CAPABILITIES = BackendCapability.GENERATE | BackendCapability.EMBED
    SDK_PACKAGE = "openai"
    CONFIG_KEY = "openai_api_key"
    ENV_VAR = "OPENAI_API_KEY"

    def _build_client(self, sdk: Any, api_key: str) -> Any:
        # OPENAI_BASE_URL points the SDK at any OpenAI-compatible server (e.g.
        # a local Ollama at http://localhost:11434/v1), so the same backend can
        # run a real benchmark offline without a hosted OpenAI key.
        kwargs: dict[str, Any] = {"api_key": api_key, "timeout": self.HTTP_TIMEOUT_S}
        base_url = os.environ.get("OPENAI_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        return sdk.OpenAI(**kwargs)

    @APIBackend._retry()
    def _chat(self, **kwargs: Any) -> Any:
        return self._get_client().chat.completions.create(model=self.model_id, **kwargs)

    @APIBackend._retry()
    def _embed_call(self, text: str) -> Any:
        return self._get_client().embeddings.create(model=_EMBEDDING_MODEL, input=text)

    def generate(
        self,
        prompt: str,
        n_samples: int = 1,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> list[Generation]:
        """Sample ``n_samples`` completions from the chat model with token logprobs."""
        if n_samples < 1:
            raise ValueError(f"n_samples must be >= 1, got {n_samples}")
        results: list[Generation] = []
        # Some OpenAI-compatible servers (Ollama, some vLLM builds) ignore n>1 and
        # return a single choice. Loop until we have n_samples so sampling-based
        # estimators (self_consistency, semantic_entropy) still work everywhere.
        while len(results) < n_samples:
            response = self._chat(
                messages=[{"role": "user", "content": prompt}],
                n=n_samples - len(results),
                temperature=temperature,
                max_tokens=max_tokens,
                logprobs=True,
            )
            if not response.choices:
                break
            for choice in response.choices:
                text = choice.message.content or ""
                scores: list[float] = []
                lp = getattr(choice, "logprobs", None)
                if lp is not None and getattr(lp, "content", None):
                    scores = [float(tok.logprob) for tok in lp.content]
                results.append(
                    Generation(
                        text=text, logprobs=scores, finish_reason=choice.finish_reason or "stop"
                    )
                )
        return results[:n_samples]

    def logprobs(self, prompt: str, completion: str) -> TokenLogProbs:
        """Raise ``NotImplementedError``: Chat Completions cannot score a user-supplied prefill."""
        raise NotImplementedError(
            "OpenAI Chat Completions returns logprobs only for newly generated "
            "tokens, not for a user-supplied completion prefill. Use HFBackend "
            "for estimators that need per-token logprobs of (prompt, completion) "
            "pairs, or switch to a sampling-based estimator (self_consistency, "
            "semantic_entropy)."
        )

    def embed(self, text: str) -> np.ndarray[Any, Any]:
        """Return the ``text-embedding-3-small`` vector for ``text`` as a float32 array."""
        response = self._embed_call(text)
        return np.asarray(response.data[0].embedding, dtype=np.float32)


__all__ = ["OpenAIBackend"]
