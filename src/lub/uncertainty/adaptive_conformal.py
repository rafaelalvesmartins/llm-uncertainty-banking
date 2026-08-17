# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Adaptive (online) conformal prediction for LLM QA refusal.

Standard split conformal (:class:`~lub.uncertainty.conformal.ConformalEstimator`)
assumes exchangeability between calibration and test data — a condition
that fails when the input distribution shifts, which in banking is the
norm (regulatory changes, market regimes, seasonal patterns).

This module implements the **Adaptive Conformal Inference** (ACI)
procedure of Gibbs & Candès (2021): after each prediction, the
miscoverage level ``alpha`` is updated online so that the running
coverage converges to ``1 - alpha_target`` even under arbitrary
distribution shift. The update rule is:

    alpha_{t+1} = alpha_t + gamma * (err_t - alpha_target)

where ``err_t = 1`` if the prediction set at step ``t`` did not cover
the true answer, and ``gamma`` is a step-size controlling adaptation
speed. Larger ``gamma`` tracks shift faster but introduces more
variance in the threshold.

Reference:
    Gibbs, I. & Candès, E. (2021). *Adaptive Conformal Inference Under
    Distribution Shift.* NeurIPS 2021.
    Angelopoulos, A. N. & Bates, S. (2024). *Conformal Risk Control.*
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Final

import structlog

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty._conformal_utils import token_logprob_nonconformity
from lub.uncertainty.base import Estimator
from lub.wrappers.base import BackendCapability

_LOG = structlog.get_logger("lub.uncertainty.adaptive_conformal")

# Clamp bounds for the online-updated alpha. Gibbs & Candès (2021) §2.1
# keep alpha in the open interval (0, 1); we use a 1e-3 margin so the
# threshold remains a finite quantile of a nonempty calibration window
# (an alpha of exactly 0 or 1 degenerates the prediction set).
_ALPHA_FLOOR: Final = 1e-3
_ALPHA_CEIL: Final = 1.0 - 1e-3
# Upper bound on gamma. The ACI proof assumes gamma is small relative to
# 1; very large values (> 1) produce divergent alpha oscillations that
# defeat the long-run coverage guarantee.
_GAMMA_MAX: Final = 1.0


class AdaptiveConformalEstimator(Estimator):
    """Online-adaptive conformal predictor (Gibbs & Candès 2021).

    Unlike :class:`ConformalEstimator`, this estimator does **not**
    require a separate ``.fit()`` call. Instead it maintains a running
    nonconformity-score history and adjusts ``alpha`` after each call
    to ``score()``. The caller must feed ground-truth labels back via
    :meth:`update` for the adaptation to work; without updates the
    estimator degrades gracefully to a fixed-alpha conformal predictor
    with an expanding calibration window.
    """

    REGISTRY_KEY = "adaptive_conformal"
    REQUIRES_CAPABILITIES = BackendCapability.GENERATE | BackendCapability.LOGPROBS

    def __init__(
        self,
        alpha_target: float = 0.1,
        gamma: float = 0.01,
        window: int = 500,
        max_tokens: int = 256,
    ) -> None:
        if not 0.0 < alpha_target < 1.0:
            raise ValueError(f"alpha_target must be in (0, 1), got {alpha_target}")
        if gamma <= 0.0:
            raise ValueError(f"gamma must be > 0, got {gamma}")
        if gamma > _GAMMA_MAX:
            raise ValueError(
                f"gamma must be <= {_GAMMA_MAX} for bounded ACI oscillation, got {gamma}"
            )
        self.alpha_target = alpha_target
        self.gamma = gamma
        self.max_tokens = max_tokens
        self._alpha = alpha_target
        self._scores: deque[float] = deque(maxlen=window)
        self._threshold: float | None = None

    @property
    def current_alpha(self) -> float:
        """Return the current online-adapted miscoverage level."""
        return self._alpha

    @property
    def threshold(self) -> float | None:
        """Return the current nonconformity threshold, or None if uncalibrated."""
        return self._threshold

    def _recompute_threshold(self) -> float | None:
        if len(self._scores) < 2:
            return None
        sorted_scores = sorted(self._scores)
        n = len(sorted_scores)
        rank = math.ceil((n + 1) * (1.0 - self._alpha))
        index = min(max(rank - 1, 0), n - 1)
        return float(sorted_scores[index])

    @staticmethod
    def _nonconformity(backend: BackendProto, prompt: str, completion: str) -> float:
        """Delegate to the shared token-logprob nonconformity scorer."""
        return token_logprob_nonconformity(backend, prompt, completion)

    def score(
        self,
        backend: BackendProto,
        prompt: str,
        **kwargs: Any,
    ) -> UncertaintyResult:
        """Generate an answer and score it against the running ACI threshold."""
        max_tokens = int(kwargs.get("max_tokens", self.max_tokens))
        generations = self._require_generations(
            backend.generate(prompt, n_samples=1, temperature=0.0, max_tokens=max_tokens)
        )
        gen = generations[0]
        nc = self._nonconformity(backend, prompt, gen.text)
        self._scores.append(nc)
        self._threshold = self._recompute_threshold()

        if self._threshold is not None:
            inside = nc <= self._threshold
            confidence = 1.0 - self._alpha if inside else 0.0
        else:
            inside = True
            confidence = 1.0 - self._alpha

        return UncertaintyResult(
            answer=gen.text,
            confidence=self._clip01(confidence),
            raw_scores={
                "nonconformity": float(nc),
                "threshold": float(self._threshold)
                if self._threshold is not None
                else float("nan"),
                "alpha": float(self._alpha),
                "alpha_target": float(self.alpha_target),
                "window_size": float(len(self._scores)),
            },
            samples=[gen.text],
            should_refuse=not inside,
        )

    def update(self, covered: bool) -> None:
        """Feed back whether the last prediction covered the true answer.

        Call this after ``score()`` with ground truth to enable the
        online alpha adaptation. Without calls to ``update``, the
        estimator keeps a fixed alpha and simply grows the calibration
        window — still useful, just not adaptive.
        """
        err = 0.0 if covered else 1.0
        self._alpha = max(
            _ALPHA_FLOOR,
            min(_ALPHA_CEIL, self._alpha + self.gamma * (err - self.alpha_target)),
        )
        self._threshold = self._recompute_threshold()


__all__ = ["AdaptiveConformalEstimator"]
