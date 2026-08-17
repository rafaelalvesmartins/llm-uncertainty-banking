# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Perplexity-based uncertainty estimator.

A simple information-based baseline: confidence is derived from the
perplexity of a single greedy generation, mapped into ``[0, 1]`` via
``exp(mean(logprobs))`` where ``mean(logprobs)`` is the mean log-probability
over the generated tokens. Lower perplexity (higher mean log-probability)
translates to higher confidence.

This is the most-cited baseline in the LLM uncertainty literature and
complements :class:`~lub.uncertainty.token_logprob.TokenLogprobEstimator`
by making the relationship to perplexity explicit in the diagnostics.

Reference:
    Fomicheva, M., Sun, S., Yankovskaya, L., Blain, F., Guzman, F.,
    Fishel, M., Aletras, N., Chaudhary, V., & Specia, L. (2020).
    *Unsupervised quality estimation for neural machine translation.*
    Transactions of the ACL, 8, 539-555.
"""

from __future__ import annotations

import math
from typing import Any

import structlog

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty._math_utils import mean_logprob_confidence
from lub.uncertainty.base import Estimator

_LOG = structlog.get_logger("lub.uncertainty.perplexity")


class PerplexityEstimator(Estimator):
    """Single-generation confidence derived from per-token perplexity."""

    REGISTRY_KEY = "perplexity"

    def __init__(self, refusal_threshold: float = 0.5) -> None:
        self.refusal_threshold = self._validate_threshold(refusal_threshold)

    def score(
        self,
        backend: BackendProto,
        prompt: str,
        **kwargs: Any,
    ) -> UncertaintyResult:
        """Compute uncertainty score for the given prompt and answer."""
        max_tokens = int(kwargs.get("max_tokens", 256))
        generations = self._require_generations(
            backend.generate(
                prompt,
                n_samples=1,
                temperature=0.0,
                max_tokens=max_tokens,
            )
        )
        gen = generations[0]

        logprobs = gen.logprobs if gen.logprobs is not None else []
        mean_logprob, confidence = mean_logprob_confidence(logprobs)
        perplexity = math.exp(-mean_logprob) if logprobs else float("inf")
        raw_scores: dict[str, float] = {
            "mean_logprob": float(mean_logprob),
            "perplexity": float(perplexity),
            "n_tokens": float(len(logprobs)),
        }
        return UncertaintyResult(
            answer=gen.text,
            confidence=confidence,
            raw_scores=raw_scores,
            samples=[gen.text],
            should_refuse=confidence < self.refusal_threshold,
        )


__all__ = ["PerplexityEstimator"]
