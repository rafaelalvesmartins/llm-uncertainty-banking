# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""TokenSAR (Shifting Attention to Relevance) uncertainty estimator.

Confidence is derived from a *relevance-weighted* mean of per-token
log-probabilities, where relevance is ``-logprob`` itself. Tokens the
model is uncertain about (low logprob, high surprise) get more weight
in the aggregate than confident boilerplate tokens. This makes the
metric more sensitive to the few critical tokens that determine answer
correctness — exactly the failure mode that matters for financial QA.

    SAR = sum(r_i * logp_i) / sum(r_i),   r_i = -logp_i
    confidence = exp(SAR)  clipped to [0, 1]

Single generation, whitebox (requires logprobs). Cost is identical
to :class:`TokenLogprobEstimator` — one forward pass — but the
weighting scheme consistently outperforms unweighted mean logprob
on selective-prediction tasks (Duan et al. 2023 Table 2).

Reference:
    Duan, J., Cheng, H., Wang, S., et al. (2023).
    *Shifting Attention to Relevance: Towards the Uncertainty
    Estimation of Large Language Models.* arXiv:2307.01379.
"""

from __future__ import annotations

import math
from typing import Any

import structlog

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty.base import Estimator

_LOG = structlog.get_logger("lub.uncertainty.sar")


class TokenSAREstimator(Estimator):
    """Duan et al. 2023 TokenSAR relevance-weighted confidence."""

    REGISTRY_KEY = "token_sar"

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
        if logprobs:
            relevance = [-lp for lp in logprobs]
            r_sum = sum(relevance)
            if r_sum > 0:
                sar = sum(r * lp for r, lp in zip(relevance, logprobs, strict=True)) / r_sum
            else:
                sar = sum(logprobs) / len(logprobs)
            confidence = math.exp(sar)
        else:
            sar = float("nan")
            confidence = 0.0

        confidence = max(0.0, min(1.0, confidence))
        raw_scores: dict[str, float] = {
            "sar": float(sar),
            "n_tokens": float(len(logprobs)),
        }
        return UncertaintyResult(
            answer=gen.text,
            confidence=confidence,
            raw_scores=raw_scores,
            samples=[gen.text],
            should_refuse=confidence < self.refusal_threshold,
        )


__all__ = ["TokenSAREstimator"]
