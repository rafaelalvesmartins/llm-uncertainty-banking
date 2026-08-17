# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""SentenceSAR — sentence-level Shifting Attention to Relevance.

Extends the token-level SAR estimator (:class:`~lub.uncertainty.sar.TokenSAREstimator`)
to operate over **multiple sampled generations**. Instead of weighting
individual tokens by their surprise, SentenceSAR:

1. Samples ``n`` completions at temperature ``T``.
2. Computes a per-generation SAR score (relevance-weighted mean logprob).
3. Weights generations by their SAR *relevance* (lower SAR = more
   surprising generation = higher weight).
4. Returns the relevance-weighted mean SAR as confidence.

This captures *inter-generation* diversity alongside *intra-generation*
token relevance. A prompt where all sampled answers agree *and* each
answer has high token-level SAR gets the highest confidence; a prompt
where answers diverge *or* individual tokens are uncertain gets low
confidence.

The method follows Duan et al. (2024, ACL) §4.2 "Sentence-level SAR"
which extends the 2023 TokenSAR paper to the sampling setting.

Reference:
    Duan, J., Cheng, H., Wang, S., et al. (2024).
    *Shifting Attention to Relevance: Towards the Predictive
    Uncertainty Quantification of Free-Form Large Language Models.*
    ACL 2024. arXiv:2307.01379v3.
"""

from __future__ import annotations

import math
from typing import Any

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty.base import Estimator


def _token_sar(logprobs: list[float]) -> float:
    """Compute token-level SAR for one generation.

    Returns ``-inf`` when ``logprobs`` is empty so downstream
    aggregators can filter with :func:`math.isfinite`; returning 0.0
    instead would silently inflate the sentence-level SAR of runs
    where the backend emitted an empty completion.
    """
    if not logprobs:
        return float("-inf")
    relevance = [-lp for lp in logprobs]
    r_sum = sum(relevance)
    if r_sum > 0:
        return sum(r * lp for r, lp in zip(relevance, logprobs, strict=True)) / r_sum
    return sum(logprobs) / len(logprobs)


class SentenceSAREstimator(Estimator):
    """Sentence-level SAR over multiple sampled generations (Duan+ 2024)."""

    REGISTRY_KEY = "sentence_sar"

    def __init__(
        self,
        n_samples: int = 5,
        temperature: float = 0.7,
        refusal_threshold: float = 0.5,
        max_tokens: int = 256,
    ) -> None:
        self.n_samples = self._validate_n_samples(n_samples, minimum=2)
        self.temperature = self._validate_temperature(temperature)
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
                n_samples=self.n_samples,
                temperature=self.temperature,
                max_tokens=max_tokens,
            )
        )

        # Compute per-generation SAR scores.
        texts: list[str] = []
        sar_scores: list[float] = []
        for gen in generations:
            texts.append(gen.text)
            lps = self._logprobs_or_empty(gen)
            sar_scores.append(_token_sar(lps))

        # Filter out degenerate generations (no logprobs at all).
        valid = [(t, s) for t, s in zip(texts, sar_scores, strict=True) if math.isfinite(s)]
        if not valid:
            return UncertaintyResult(
                answer=texts[0] if texts else "",
                confidence=0.0,
                raw_scores={
                    "sentence_sar": float("nan"),
                    "n_valid": 0.0,
                    "n_samples": float(len(texts)),
                },
                samples=texts,
                should_refuse=True,
            )

        valid_texts, valid_sars = zip(*valid, strict=True)

        # Sentence-level relevance weighting: weight_i = -SAR_i
        # (more negative SAR = more surprising = higher weight).
        relevances = [-s for s in valid_sars]
        r_sum = sum(relevances)
        if r_sum > 0:
            sentence_sar = sum(r * s for r, s in zip(relevances, valid_sars, strict=True)) / r_sum
        else:
            sentence_sar = sum(valid_sars) / len(valid_sars)

        confidence = self._clip01(math.exp(sentence_sar))

        # Pick the generation with the highest individual SAR as the answer.
        best_idx = max(range(len(valid_sars)), key=lambda i: valid_sars[i])

        return UncertaintyResult(
            answer=valid_texts[best_idx],
            confidence=confidence,
            raw_scores={
                "sentence_sar": float(sentence_sar),
                "mean_token_sar": float(sum(valid_sars) / len(valid_sars)),
                "min_token_sar": float(min(valid_sars)),
                "max_token_sar": float(max(valid_sars)),
                "n_valid": float(len(valid_sars)),
                "n_samples": float(len(texts)),
            },
            samples=list(texts),
            should_refuse=confidence < self.refusal_threshold,
        )


__all__ = ["SentenceSAREstimator"]
