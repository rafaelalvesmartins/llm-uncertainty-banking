# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Sampling-based conformal prediction with dual admission/rejection rules.

Extends the split-conformal procedure in
:class:`~lub.uncertainty.conformal.ConformalEstimator` with a
sampling-based approach inspired by Quach et al. (2024). Instead of
evaluating a single greedy generation, the estimator generates ``k``
candidate completions and applies two calibrated thresholds:

1. **Admission rule** — a completion is admitted to the prediction set
   if its nonconformity score is ≤ ``tau_admit`` (the calibrated
   ``(1 - alpha)`` quantile, identical to split-conformal).
2. **Rejection rule** — if fewer than ``min_admit`` completions pass
   the admission rule, the entire prompt is refused. This catches
   cases where the model *can* produce one lucky good answer but is
   generally unreliable on the prompt.

The combination gives a distribution-free marginal coverage guarantee
on the admitted set *and* a principled refusal mechanism for prompts
where the model is broadly uncertain — exactly the "when to trust"
signal SR 11-7 reviewers ask for.

Confidence is the fraction of admitted samples, which is monotone in
the model's agreement with itself under the calibrated threshold.

Reference:
    Quach, V., Fisch, A., Schuster, T., Yala, A., Sohn, J. H.,
    Jaakkola, T. S., & Barzilay, R. (2024). *Conformal Language
    Modeling.* ICLR 2024. arXiv:2306.10193.
"""

from __future__ import annotations

import math
from typing import Any

import structlog

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty._conformal_utils import token_logprob_nonconformity
from lub.uncertainty.base import Estimator
from lub.wrappers.base import BackendCapability

_LOG = structlog.get_logger("lub.uncertainty.conformal_sampling")


class ConformalSamplingEstimator(Estimator):
    """Sampling-based conformal predictor with dual admission/rejection."""

    REGISTRY_KEY = "conformal_sampling"
    REQUIRES_CAPABILITIES = BackendCapability.GENERATE | BackendCapability.LOGPROBS

    def __init__(
        self,
        alpha: float = 0.1,
        n_samples: int = 10,
        temperature: float = 0.7,
        min_admit_fraction: float = 0.3,
    ) -> None:
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        n_samples = self._validate_n_samples(n_samples, minimum=2)
        temperature = self._validate_temperature(temperature)
        if not 0.0 <= min_admit_fraction <= 1.0:
            raise ValueError(f"min_admit_fraction must be in [0, 1], got {min_admit_fraction}")
        self.alpha = alpha
        self.n_samples = n_samples
        self.temperature = temperature
        self.min_admit_fraction = min_admit_fraction
        self.tau_admit: float | None = None
        self.n_calibration: int = 0

    @property
    def min_admit(self) -> int:
        """Return the minimum admitted-sample count required to avoid refusal."""
        return max(1, math.ceil(self.n_samples * self.min_admit_fraction))

    def fit(
        self,
        calibration_set: list[tuple[str, str]],
        *,
        backend: BackendProto,
    ) -> None:
        """Calibrate tau_admit from held-out (prompt, gold) pairs."""
        if not calibration_set:
            raise ValueError("calibration_set must be non-empty")
        scores = [token_logprob_nonconformity(backend, p, g) for p, g in calibration_set]
        scores_sorted = sorted(scores)
        n = len(scores_sorted)
        rank = math.ceil((n + 1) * (1.0 - self.alpha))
        index = min(max(rank - 1, 0), n - 1)
        self.tau_admit = float(scores_sorted[index])
        self.n_calibration = n

    def score(
        self,
        backend: BackendProto,
        prompt: str,
        **kwargs: Any,
    ) -> UncertaintyResult:
        """Generate samples and return calibrated confidence with refusal flag."""
        if self.tau_admit is None:
            raise RuntimeError("ConformalSamplingEstimator.fit must be called before score")
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
        nonconformities = [token_logprob_nonconformity(backend, prompt, t) for t in texts]
        admitted = [
            (t, nc) for t, nc in zip(texts, nonconformities, strict=True) if nc <= self.tau_admit
        ]
        n_admitted = len(admitted)
        confidence = n_admitted / self.n_samples
        should_refuse = n_admitted < self.min_admit

        if admitted:
            best_text, _ = min(admitted, key=lambda x: x[1])
        else:
            best_idx = min(range(len(nonconformities)), key=nonconformities.__getitem__)
            best_text = texts[best_idx]

        raw_scores: dict[str, float] = {
            "n_admitted": float(n_admitted),
            "n_samples": float(self.n_samples),
            "admission_rate": confidence,
            "tau_admit": float(self.tau_admit),
            "min_admit": float(self.min_admit),
            "mean_nonconformity": float(sum(nonconformities) / len(nonconformities)),
        }
        return UncertaintyResult(
            answer=best_text,
            confidence=max(0.0, min(1.0, confidence)),
            raw_scores=raw_scores,
            samples=texts,
            should_refuse=should_refuse,
        )


__all__ = ["ConformalSamplingEstimator"]
