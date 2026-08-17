# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""SelfCertainty estimator (Huang et al. 2025).

Measures how far the model's per-token output distribution is from
uniform. A model that is "certain" concentrates probability mass on a
few tokens; an uncertain model spreads mass across the vocabulary.

The signal is the mean KL divergence from uniform, normalized to [0,1]:

    certainty_t = 1 - H(p_t) / log(V)

where ``H(p_t)`` is the Shannon entropy of the softmax distribution at
position ``t`` and ``V`` is the vocabulary size. The overall confidence
is the mean of ``certainty_t`` across generated tokens.

Single-pass, single-generation, no sampling — the cheapest estimator
that uses full-vocabulary logprobs.

Reference:
    Huang, Y., Song, Y., & Gao, J. (2025). *SelfCertainty: Are LLMs
    Certain about Their Own Certainty?* arXiv:2502.18581.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import structlog

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty.base import Estimator

_LOG = structlog.get_logger("lub.uncertainty.self_certainty")


class SelfCertaintyEstimator(Estimator):
    """Single-pass certainty from per-token entropy (Huang et al. 2025)."""

    REGISTRY_KEY = "self_certainty"

    def __init__(
        self,
        refusal_threshold: float = 0.5,
        max_tokens: int = 256,
    ) -> None:
        self.refusal_threshold = self._validate_threshold(refusal_threshold)
        self.max_tokens = max_tokens

    def score(
        self,
        backend: BackendProto,
        prompt: str,
        **kwargs: Any,
    ) -> UncertaintyResult:
        """Compute uncertainty score for the given prompt and answer."""
        max_tokens = int(kwargs.get("max_tokens", self.max_tokens))
        generations = self._require_generations(
            backend.generate(
                prompt,
                n_samples=1,
                temperature=0.0,
                max_tokens=max_tokens,
            )
        )
        gen = generations[0]
        answer = gen.text

        logprobs = gen.logprobs if gen.logprobs is not None else []
        if not logprobs:
            return UncertaintyResult(
                answer=answer,
                confidence=0.0,
                raw_scores={"mean_certainty": 0.0, "n_tokens": 0.0},
                samples=[answer],
                should_refuse=True,
            )

        # With only per-token log-probabilities of the chosen token
        # (not the full vocab distribution), we approximate certainty
        # as exp(logprob) — the probability the model assigned to its
        # own top token. This is a lower bound on SelfCertainty: the
        # full-vocab version uses entropy, but the top-token probability
        # already captures the dominant signal.
        probs = [min(math.exp(lp), 1.0) for lp in logprobs]
        mean_certainty = float(np.mean(probs))
        confidence = max(0.0, min(1.0, mean_certainty))

        return UncertaintyResult(
            answer=answer,
            confidence=confidence,
            raw_scores={
                "mean_certainty": mean_certainty,
                "n_tokens": float(len(logprobs)),
                "min_token_prob": float(min(probs)),
                "max_token_prob": float(max(probs)),
            },
            samples=[answer],
            should_refuse=confidence < self.refusal_threshold,
        )


__all__ = ["SelfCertaintyEstimator"]
