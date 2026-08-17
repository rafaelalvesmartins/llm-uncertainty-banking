# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Token log-probability estimator.

Confidence is the geometric mean of per-token probabilities of a single
greedy-ish generation, i.e. ``exp(mean(logprobs))``. This is the simplest
baseline: cheap, single-pass, but miscalibrated on open-ended generation.

Reference:
    Kadavath, S., Conerly, T., Askell, A., et al. (2022). *Language
    Models (Mostly) Know What They Know.* arXiv:2207.05221. (Token
    log-probability as a baseline confidence signal.)
"""

from __future__ import annotations

from typing import Any

import structlog

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty._math_utils import mean_logprob_confidence
from lub.uncertainty.base import Estimator

_LOG = structlog.get_logger("lub.uncertainty.token_logprob")


class TokenLogprobEstimator(Estimator):
    """Single-generation confidence from mean token log-probability."""

    REGISTRY_KEY = "token_logprob"

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
        raw_scores: dict[str, float] = {
            "mean_logprob": float(mean_logprob),
            "n_tokens": float(len(logprobs)),
        }
        return UncertaintyResult(
            answer=gen.text,
            confidence=confidence,
            raw_scores=raw_scores,
            samples=[gen.text],
            should_refuse=confidence < self.refusal_threshold,
        )


__all__ = ["TokenLogprobEstimator"]
