# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Deterministic in-process backend used for unit tests and examples.

DummyBackend makes no network calls, requires no model weights, and returns
values that are a pure function of the input. This keeps tests fast (<5s),
hermetic, and reproducible across machines.
"""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import structlog

from lub.types import Generation, TokenLogProbs
from lub.wrappers.base import BackendCapability, ModelBackend

_LOG = structlog.get_logger("lub.wrappers.dummy")

_EMBED_DIM = 8


def _seed_from_text(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


class DummyBackend(ModelBackend):
    """Deterministic, offline backend for testing."""

    REGISTRY_KEY = "dummy"
    CAPABILITIES = BackendCapability.GENERATE | BackendCapability.LOGPROBS | BackendCapability.EMBED

    def __init__(self, model_id: str = "dummy-0") -> None:
        super().__init__(model_id)

    def generate(
        self,
        prompt: str,
        n_samples: int = 1,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> list[Generation]:
        """Return ``n_samples`` deterministic generations seeded from the prompt."""
        if n_samples < 1:
            raise ValueError(f"n_samples must be >= 1, got {n_samples}")
        seed = _seed_from_text(prompt)
        rng = np.random.default_rng(seed)
        results: list[Generation] = []
        for i in range(n_samples):
            token_count = 1 + (rng.integers(0, 4) if temperature > 0 else 0)
            tag = hashlib.sha256(f"{prompt}|{i}".encode()).hexdigest()[:8]
            text = f"dummy-answer-{tag}"
            logprobs = [-1.0] * int(token_count)
            results.append(Generation(text=text, logprobs=logprobs, finish_reason="stop"))
        return results

    def logprobs(self, prompt: str, completion: str) -> TokenLogProbs:
        """Return constant per-token log-probabilities for the prompt's whitespace tokens."""
        tokens = prompt.split()
        return TokenLogProbs(tokens=tokens, logprobs=[-1.0] * len(tokens))

    def embed(self, text: str) -> np.ndarray[Any, Any]:
        """Return a deterministic L2-normalized embedding seeded from ``text``."""
        rng = np.random.default_rng(_seed_from_text(text))
        vec = rng.standard_normal(_EMBED_DIM)
        norm = float(np.linalg.norm(vec))
        if norm == 0.0:
            return vec
        return vec / norm


__all__ = ["DummyBackend"]
