# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Ensemble uncertainty estimator — weighted blend of sub-estimators.

Runs ``k`` estimators against the same prompt and backend, collects
their confidences, and returns a weighted average as the ensemble
confidence. The answer text is taken from the sub-estimator with the
highest individual confidence (most-confident-wins selection).

This mirrors the ``TunableEnsemble`` pattern in CVS Health's UQLM
library (github.com/cvs-health/uqlm, Apache-2.0): a composite scorer
that blends token-probability, consistency, and LLM-judge signals
into a single ``[0, 1]`` confidence. LUB's implementation is simpler
(no fitted weights by default) but accepts custom weight vectors for
calibrated blending after a dev-split sweep.

Reference:
    CVS Health / UQLM, "Uncertainty Quantification for Language
    Models," arXiv:2507.06196 (2025).
"""

from __future__ import annotations

from typing import Any

import structlog

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty.base import Estimator

_LOG = structlog.get_logger("lub.uncertainty.ensemble")


class EnsembleEstimator(Estimator):
    """Weighted ensemble of sub-estimators."""

    REGISTRY_KEY = "ensemble"

    def __init__(
        self,
        estimators: list[Estimator],
        weights: list[float] | None = None,
        refusal_threshold: float = 0.5,
    ) -> None:
        if len(estimators) < 2:
            raise ValueError(f"ensemble requires >= 2 estimators, got {len(estimators)}")
        if weights is not None:
            if len(weights) != len(estimators):
                raise ValueError(
                    f"weights length ({len(weights)}) must match "
                    f"estimators length ({len(estimators)})"
                )
            if any(w < 0 for w in weights):
                raise ValueError("all weights must be >= 0")
            w_sum = sum(weights)
            if w_sum == 0:
                raise ValueError("weights must not all be zero")
            self._weights = [w / w_sum for w in weights]
        else:
            n = len(estimators)
            self._weights = [1.0 / n] * n
        self.estimators = list(estimators)
        self.refusal_threshold = self._validate_threshold(refusal_threshold)

    def score(
        self,
        backend: BackendProto,
        prompt: str,
        **kwargs: Any,
    ) -> UncertaintyResult:
        """Compute uncertainty score for the given prompt and answer."""
        results: list[UncertaintyResult] = []
        for est in self.estimators:
            results.append(est.score(backend, prompt, **kwargs))

        confidence = sum(w * r.confidence for w, r in zip(self._weights, results, strict=True))
        confidence = max(0.0, min(1.0, confidence))

        best_idx = max(range(len(results)), key=lambda i: results[i].confidence)
        answer = results[best_idx].answer

        raw_scores: dict[str, float] = {
            "ensemble_confidence": confidence,
            "n_estimators": float(len(self.estimators)),
        }
        for i, (est, r) in enumerate(zip(self.estimators, results, strict=True)):
            raw_scores[f"{est.REGISTRY_KEY}_confidence"] = r.confidence
            raw_scores[f"{est.REGISTRY_KEY}_weight"] = self._weights[i]

        all_samples: list[str] = []
        for r in results:
            all_samples.extend(r.samples or [])

        return UncertaintyResult(
            answer=answer,
            confidence=confidence,
            raw_scores=raw_scores,
            samples=all_samples,
            should_refuse=confidence < self.refusal_threshold,
        )


__all__ = ["EnsembleEstimator"]
