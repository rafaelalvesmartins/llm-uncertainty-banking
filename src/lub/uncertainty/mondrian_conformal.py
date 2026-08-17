# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Mondrian (group-conditional) conformal prediction.

Standard conformal prediction provides *marginal* coverage — 1-alpha
coverage on average across the entire population. In banking this is
insufficient: a model that systematically under-covers one demographic
group while over-covering another can satisfy marginal guarantees
while violating fair-lending requirements.

Mondrian conformal prediction (Vovk 2005, Chapter 8) stratifies the
calibration set by a categorical group attribute and computes a
separate nonconformity threshold per group. Each group then gets its
own 1-alpha coverage guarantee.

For LUB, the group attribute is any field in
``Example.metadata`` (e.g., ``topic``, ``source_url``, demographic
category). The estimator delegates nonconformity scoring to token
logprobs (same as :class:`ConformalEstimator`).

Reference:
    Vovk, V. (2005). *Algorithmic Learning in a Random World.*
    Springer. Chapter 8 (Mondrian conformal predictors).
"""

from __future__ import annotations

import math
import zlib
from typing import Any

import structlog

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty._conformal_utils import token_logprob_nonconformity
from lub.uncertainty.base import Estimator
from lub.wrappers.base import BackendCapability

_LOG = structlog.get_logger("lub.uncertainty.mondrian_conformal")


class MondrianConformalEstimator(Estimator):
    """Group-conditional conformal predictor (Vovk 2005).

    Call :meth:`fit` with a calibration set that includes group labels.
    At inference time, ``score()`` requires a ``group`` kwarg to select
    the per-group threshold.
    """

    REGISTRY_KEY = "mondrian_conformal"
    REQUIRES_CAPABILITIES = BackendCapability.GENERATE | BackendCapability.LOGPROBS

    def __init__(self, alpha: float = 0.1) -> None:
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        self.alpha = alpha
        self.thresholds: dict[str, float] = {}
        self.n_per_group: dict[str, int] = {}

    @staticmethod
    def _nonconformity(backend: BackendProto, prompt: str, completion: str) -> float:
        """Delegate to the shared token-logprob nonconformity scorer."""
        return token_logprob_nonconformity(backend, prompt, completion)

    def fit(
        self,
        calibration_set: list[tuple[str, str, str]],
        *,
        backend: BackendProto,
    ) -> None:
        """Fit per-group thresholds from a calibration set.

        ``calibration_set`` is a list of ``(prompt, gold_answer, group)``
        triples. Each group gets its own (1-alpha) quantile threshold.
        """
        if not calibration_set:
            raise ValueError("calibration_set must be non-empty")
        by_group: dict[str, list[float]] = {}
        for prompt, gold, group in calibration_set:
            nc = self._nonconformity(backend, prompt, gold)
            by_group.setdefault(group, []).append(nc)

        for group, scores in by_group.items():
            scores_sorted = sorted(scores)
            n = len(scores_sorted)
            rank = math.ceil((n + 1) * (1.0 - self.alpha))
            index = min(max(rank - 1, 0), n - 1)
            self.thresholds[group] = float(scores_sorted[index])
            self.n_per_group[group] = n

    def score(
        self,
        backend: BackendProto,
        prompt: str,
        **kwargs: Any,
    ) -> UncertaintyResult:
        """Compute uncertainty score for the given prompt and answer."""
        if not self.thresholds:
            raise RuntimeError("MondrianConformalEstimator.fit must be called before score")
        group = str(kwargs.get("group", "default"))
        max_tokens = int(kwargs.get("max_tokens", 256))

        generations = self._require_generations(
            backend.generate(prompt, n_samples=1, temperature=0.0, max_tokens=max_tokens)
        )
        gen = generations[0]
        nc = self._nonconformity(backend, prompt, gen.text)

        if group in self.thresholds:
            threshold = self.thresholds[group]
        else:
            threshold = max(self.thresholds.values())

        inside = nc <= threshold
        confidence = self._clip01(1.0 - self.alpha if inside else 0.0)

        return UncertaintyResult(
            answer=gen.text,
            confidence=confidence,
            raw_scores={
                "nonconformity": float(nc),
                "threshold": float(threshold),
                "alpha": float(self.alpha),
                "group": float(zlib.crc32(group.encode("utf-8")) % 1000),
                "n_groups": float(len(self.thresholds)),
            },
            diagnostics={"group_name": group, "group_thresholds": dict(self.thresholds)},
            samples=[gen.text],
            should_refuse=not inside,
        )


__all__ = ["MondrianConformalEstimator"]
