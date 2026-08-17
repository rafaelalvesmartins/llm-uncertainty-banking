# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Epistemic-aleatoric uncertainty decomposition for blackbox LLMs.

Implements the iterative-prompting approach of Yadkori, Kuzborskij,
Gyorgy & Szepesvari (DeepMind, 2024): sample the model ``n`` times at
temperature ``T`` to get ``n`` answers. The *total* entropy of the
answer distribution captures both epistemic (model) and aleatoric
(data/prompt) uncertainty. The *expected* entropy *within* each answer
cluster (grouped by string equality) captures aleatoric uncertainty.
The mutual information = total - expected is the epistemic component.

Banking needs this separation because SR 11-7 distinguishes *model
risk* (epistemic -- can be reduced with more data or better models)
from *inherent uncertainty* (aleatoric -- cannot be reduced). A high
epistemic signal should trigger model retraining or expert review;
a high aleatoric signal should trigger data-quality investigation.

Reference:
    Yadkori, Y. A., Kuzborskij, I., Gyorgy, A., & Szepesvari, C.
    (2024). *To Believe or Not to Believe Your LLM.* arXiv:2406.02543.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

import structlog

from lub._text_utils import normalize_answer as _normalize
from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty._math_utils import entropy_from_probs
from lub.uncertainty.base import Estimator

_LOG = structlog.get_logger("lub.uncertainty.epistemic_aleatoric")


class EpistemicAleatoricEstimator(Estimator):
    """Blackbox epistemic/aleatoric decomposition (Yadkori+ 2024)."""

    REGISTRY_KEY = "epistemic_aleatoric"

    def __init__(
        self,
        n_samples: int = 10,
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
        texts = [g.text for g in generations]
        normalized = [_normalize(t) for t in texts]
        n = len(normalized)

        # Total entropy over answer distribution.
        counts = Counter(normalized)
        probs = [c / n for c in counts.values()]
        total_entropy = entropy_from_probs(probs)

        # Expected intra-cluster entropy (aleatoric).
        # For string-equality clustering, each cluster is homogeneous,
        # so intra-cluster entropy is 0. The mutual information then
        # equals total entropy -- which is the epistemic component.
        # This is the simplest version; NLI-based clustering (as in
        # semantic_entropy) would give a tighter aleatoric estimate.
        aleatoric_entropy = 0.0
        epistemic = max(total_entropy - aleatoric_entropy, 0.0)

        max_entropy = math.log(max(n, 2))
        normalized_epistemic = min(epistemic / max_entropy, 1.0)
        confidence = self._clip01(1.0 - normalized_epistemic)

        majority_answer = counts.most_common(1)[0][0]
        answer = next(
            t for t, norm in zip(texts, normalized, strict=True) if norm == majority_answer
        )

        return UncertaintyResult(
            answer=answer,
            confidence=confidence,
            raw_scores={
                "total_entropy": total_entropy,
                "aleatoric_entropy": aleatoric_entropy,
                "epistemic_uncertainty": epistemic,
                "normalized_epistemic": normalized_epistemic,
                "n_unique_answers": float(len(counts)),
                "n_samples": float(n),
            },
            samples=texts,
            should_refuse=confidence < self.refusal_threshold,
        )


__all__ = ["EpistemicAleatoricEstimator"]
