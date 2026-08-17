# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Self-consistency estimator (Wang et al. 2022).

Sample ``n`` generations at non-zero temperature, normalize answers, and
take the majority vote. Confidence is the fraction of samples agreeing with
the majority answer. Simple, model-agnostic, and a strong baseline on
QA-style tasks where answers are short strings.

Reference:
    Wang, X., Wei, J., Schuurmans, D., Le, Q., Chi, E., Narang, S.,
    Chowdhery, A., & Zhou, D. (2023). *Self-Consistency Improves Chain
    of Thought Reasoning in Language Models.* ICLR 2023.
    arXiv:2203.11171.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import structlog

from lub._text_utils import normalize_answer as _normalize_answer
from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty.base import Estimator

_LOG = structlog.get_logger("lub.uncertainty.self_consistency")


class SelfConsistencyEstimator(Estimator):
    """Majority-vote confidence over ``n`` sampled generations."""

    REGISTRY_KEY = "self_consistency"

    def __init__(
        self,
        n_samples: int = 10,
        temperature: float = 0.7,
        refusal_threshold: float = 0.5,
    ) -> None:
        self.n_samples = self._validate_n_samples(n_samples, minimum=1)
        self.temperature = self._validate_temperature(temperature)
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
                n_samples=self.n_samples,
                temperature=self.temperature,
                max_tokens=max_tokens,
            )
        )

        raw_texts = [g.text for g in generations]
        normalized = [_normalize_answer(t) for t in raw_texts]
        counts = Counter(normalized)
        majority_norm, majority_count = counts.most_common(1)[0]

        answer = next(
            raw for raw, norm in zip(raw_texts, normalized, strict=True) if norm == majority_norm
        )
        confidence = majority_count / len(normalized)
        unique_answers = len(counts)

        raw_scores: dict[str, float] = {
            "agreement": float(confidence),
            "majority_count": float(majority_count),
            "n_samples": float(len(normalized)),
            "unique_answers": float(unique_answers),
        }
        return UncertaintyResult(
            answer=answer,
            confidence=confidence,
            raw_scores=raw_scores,
            samples=raw_texts,
            should_refuse=confidence < self.refusal_threshold,
        )


__all__ = ["SelfConsistencyEstimator"]
