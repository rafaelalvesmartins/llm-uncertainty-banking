# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Semantic entropy uncertainty estimator.

Implements the method of Kuhn, Gal, and Farquhar (2023), "Semantic
Uncertainty: Linguistic Invariances for Uncertainty Estimation in Natural
Language Generation" (ICLR 2023). The estimator samples multiple
generations, clusters them by bidirectional NLI entailment, estimates
cluster probabilities from length-normalized joint log-likelihood, and
returns entropy over the cluster distribution.
"""

from __future__ import annotations

import math
from typing import Any

from lub.protocols import BackendProto
from lub.types import Generation, UncertaintyResult
from lub.uncertainty._math_utils import entropy_from_probs, stable_softmax
from lub.uncertainty.base import Estimator

_DEFAULT_NLI_MODEL = "cross-encoder/nli-deberta-v3-small"


class SemanticEntropyEstimator(Estimator):
    """Sample-then-cluster semantic entropy estimator (Kuhn et al., 2023)."""

    REGISTRY_KEY = "semantic_entropy"

    def __init__(
        self,
        n_samples: int = 10,
        temperature: float = 1.0,
        max_tokens: int = 256,
        nli_model: str = _DEFAULT_NLI_MODEL,
        entailment_threshold: float = 0.5,
        refusal_threshold: float = 0.5,
    ) -> None:
        self.n_samples = self._validate_n_samples(n_samples, minimum=2)
        self.temperature = self._validate_temperature(temperature)
        self.max_tokens = max_tokens
        self.nli_model = nli_model
        self.entailment_threshold = self._validate_threshold(
            entailment_threshold, name="entailment_threshold"
        )
        self.refusal_threshold = self._validate_threshold(refusal_threshold)
        self._nli: Any = None
        self._nli_loaded = False

    def _load_nli(self) -> Any:
        if self._nli_loaded:
            return self._nli
        self._nli_loaded = True
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            return None
        try:
            self._nli = CrossEncoder(self.nli_model)
        except Exception as exc:
            import structlog

            structlog.get_logger(__name__).warning(
                "semantic_entropy.nli_load_failed",
                model=self.nli_model,
                error=str(exc),
                fallback="string_equality",
            )
            self._nli = None
        return self._nli

    def _entails(self, nli: Any, premise: str, hypothesis: str) -> bool:
        scores = nli.predict([(premise, hypothesis)])
        row = scores[0]
        try:
            entail_score = float(row[-1])
        except (TypeError, IndexError):
            entail_score = float(row)
        return entail_score >= self.entailment_threshold

    def _bidirectional_equivalent(self, nli: Any, a: str, b: str) -> bool:
        if a.strip() == b.strip():
            return True
        if nli is None:
            return a.strip().lower() == b.strip().lower()
        return self._entails(nli, a, b) and self._entails(nli, b, a)

    def _cluster(self, texts: list[str]) -> list[list[int]]:
        nli = self._load_nli()
        clusters: list[list[int]] = []
        for i, text in enumerate(texts):
            placed = False
            for cluster in clusters:
                rep = texts[cluster[0]]
                if self._bidirectional_equivalent(nli, rep, text):
                    cluster.append(i)
                    placed = True
                    break
            if not placed:
                clusters.append([i])
        return clusters

    @staticmethod
    def _length_normalized_loglik(gen: Generation) -> float:
        if not gen.logprobs:
            return 0.0
        return sum(gen.logprobs) / max(len(gen.logprobs), 1)

    def score(
        self,
        backend: BackendProto,
        prompt: str,
        **kwargs: Any,
    ) -> UncertaintyResult:
        """Compute uncertainty score for the given prompt and answer."""
        generations = self._require_generations(
            backend.generate(
                prompt,
                n_samples=self.n_samples,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        )
        texts = [g.text for g in generations]
        clusters = self._cluster(texts)

        cluster_logweights: list[float] = []
        for cluster in clusters:
            ll = max(self._length_normalized_loglik(generations[idx]) for idx in cluster)
            cluster_logweights.append(ll)

        probs = stable_softmax(cluster_logweights)

        entropy = entropy_from_probs(probs)
        max_entropy = math.log(max(self.n_samples, 2))
        confidence = 1.0 - min(entropy / max_entropy, 1.0)

        best_cluster_idx = max(range(len(clusters)), key=lambda i: probs[i])
        best_member = clusters[best_cluster_idx][0]
        answer = texts[best_member]

        should_refuse = confidence < self.refusal_threshold
        return UncertaintyResult(
            answer=answer,
            confidence=confidence,
            raw_scores={
                "entropy": entropy,
                "n_clusters": float(len(clusters)),
                "top_cluster_prob": probs[best_cluster_idx],
            },
            samples=texts,
            should_refuse=should_refuse,
        )


__all__ = ["SemanticEntropyEstimator"]
