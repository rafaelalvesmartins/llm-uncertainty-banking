# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Mahalanobis-distance density estimator over sampled embeddings.

Generates ``n`` completions, embeds each via the backend, and computes
the mean Mahalanobis distance of each sample from the centroid of
the sample set. A tight cluster (low mean distance) maps to high
confidence; a spread-out set (high mean distance) maps to low
confidence.

Unlike :class:`EigenScoreEstimator`, which measures spectral diversity
of the centered Gram matrix, Mahalanobis explicitly accounts for
covariance structure — correlated dimensions do not inflate the
distance. The tradeoff is that the sample covariance is rank-deficient
when ``n_samples < embedding_dim`` (the typical regime for LLM-scale
embeddings), so a regularized pseudoinverse is used.

Reference:
    Ren, J., Luo, J., Zhao, Y., et al. (2023).
    *Out-of-Distribution Detection and Selective Generation for
    Conditional Language Models.* arXiv:2209.15558.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import structlog

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty.base import Estimator
from lub.wrappers.base import BackendCapability

_LOG = structlog.get_logger("lub.uncertainty.mahalanobis")


class MahalanobisEstimator(Estimator):
    """Sample-set Mahalanobis distance as an uncertainty signal."""

    REGISTRY_KEY = "mahalanobis"
    REQUIRES_CAPABILITIES = BackendCapability.GENERATE | BackendCapability.EMBED

    def __init__(
        self,
        n_samples: int = 10,
        temperature: float = 0.7,
        reg: float = 1e-6,
        refusal_threshold: float = 0.5,
    ) -> None:
        self.n_samples = self._validate_n_samples(n_samples, minimum=2)
        self.temperature = self._validate_temperature(temperature)
        self.reg = float(reg)
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
        texts = [g.text for g in generations]

        try:
            embeddings = np.stack([backend.embed(t) for t in texts], axis=0)
        except (NotImplementedError, TypeError) as exc:
            raise TypeError(
                f"{type(backend).__name__} does not support embed(); "
                "MahalanobisEstimator requires a whitebox backend with embeddings"
            ) from exc

        mean = embeddings.mean(axis=0, keepdims=True)
        centered = embeddings - mean
        cov = (centered.T @ centered) / max(self.n_samples - 1, 1)
        cov += self.reg * np.eye(cov.shape[0])

        try:
            cov_inv = np.linalg.inv(cov)
        except np.linalg.LinAlgError:
            cov_inv = np.linalg.pinv(cov)

        diffs = embeddings - mean
        distances = np.sqrt(np.sum(diffs @ cov_inv * diffs, axis=1))
        mean_distance = float(distances.mean())

        # Map distance to confidence via exp(-d). For well-clustered
        # samples d ~ 0 → confidence ~ 1; for spread samples d >> 0
        # → confidence → 0.
        confidence = math.exp(-mean_distance)
        confidence = max(0.0, min(1.0, confidence))

        sims = (embeddings @ mean.T).ravel()
        best_idx = int(np.argmax(sims))
        answer = texts[best_idx]

        raw_scores: dict[str, float] = {
            "mean_mahalanobis": mean_distance,
            "max_mahalanobis": float(distances.max()),
            "min_mahalanobis": float(distances.min()),
            "n_samples": float(self.n_samples),
        }
        return UncertaintyResult(
            answer=answer,
            confidence=confidence,
            raw_scores=raw_scores,
            samples=texts,
            should_refuse=confidence < self.refusal_threshold,
        )


__all__ = ["MahalanobisEstimator"]
