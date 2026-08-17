# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Split conformal prediction for LLM QA refusal.

Implements the standard split-conformal procedure: fit nonconformity
scores on a held-out calibration set, take the ``(1 - alpha)`` empirical
quantile as a threshold, and refuse at inference time when a new prompt's
nonconformity exceeds that threshold. Under exchangeability, this gives a
marginal coverage guarantee of at least ``1 - alpha`` on the kept answers.

Reference:
    Vovk, V., Gammerman, A., & Shafer, G. (2005). *Algorithmic Learning
    in a Random World*. Springer.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import structlog

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty._conformal_utils import token_logprob_nonconformity
from lub.uncertainty.base import Estimator
from lub.wrappers.base import BackendCapability

_LOG = structlog.get_logger("lub.uncertainty.conformal")


class ConformalEstimator(Estimator):
    """Split conformal predictor wrapping a token-logprob base scorer."""

    REGISTRY_KEY = "conformal"
    REQUIRES_CAPABILITIES = BackendCapability.GENERATE | BackendCapability.LOGPROBS

    def __init__(self, alpha: float = 0.1) -> None:
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        self.alpha = alpha
        self.threshold: float | None = None
        self.n_calibration: int = 0

    def fit(
        self,
        calibration_set: list[tuple[str, str]],
        *,
        backend: BackendProto,
    ) -> None:
        """Fit the conformal threshold from a calibration set.

        ``calibration_set`` is a list of ``(prompt, gold_answer)`` pairs.
        The ``(1 - alpha)`` empirical quantile of per-example nonconformity
        scores is stored as :attr:`threshold`.
        """
        if not calibration_set:
            raise ValueError("calibration_set must be non-empty")

        scores = [
            token_logprob_nonconformity(backend, prompt, gold) for prompt, gold in calibration_set
        ]
        scores_sorted = sorted(scores)
        n = len(scores_sorted)
        # Finite-sample corrected quantile level: ceil((n+1)(1-alpha)) / n
        rank = math.ceil((n + 1) * (1.0 - self.alpha))
        index = min(max(rank - 1, 0), n - 1)
        self.threshold = float(scores_sorted[index])
        self.n_calibration = n

    def score(
        self,
        backend: BackendProto,
        prompt: str,
        **kwargs: Any,
    ) -> UncertaintyResult:
        """Compute uncertainty score for the given prompt and answer."""
        if self.threshold is None:
            raise RuntimeError("ConformalEstimator.fit must be called before score")

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

        nonconformity = token_logprob_nonconformity(backend, prompt, gen.text)
        inside = nonconformity <= self.threshold
        confidence = 1.0 - self.alpha if inside else 0.0

        raw_scores: dict[str, float] = {
            "nonconformity": float(nonconformity),
            "threshold": float(self.threshold),
            "alpha": float(self.alpha),
        }
        return UncertaintyResult(
            answer=gen.text,
            confidence=confidence,
            raw_scores=raw_scores,
            samples=[gen.text],
            should_refuse=not inside,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the fitted estimator state to a JSON-safe dict."""
        return {
            "type": "ConformalEstimator",
            "alpha": self.alpha,
            "threshold": self.threshold,
            "n_calibration": self.n_calibration,
        }

    def save(self, path: str | Path) -> None:
        """Write the fitted estimator to ``path`` as JSON."""
        Path(path).write_text(json.dumps(self.to_dict(), sort_keys=True), encoding="utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConformalEstimator:
        """Rebuild a fitted estimator from a :meth:`to_dict` payload."""
        if data.get("type") != "ConformalEstimator":
            raise ValueError(f"unexpected type tag: {data.get('type')!r}")
        inst = cls(alpha=float(data["alpha"]))
        threshold = data.get("threshold")
        inst.threshold = None if threshold is None else float(threshold)
        inst.n_calibration = int(data.get("n_calibration", 0))
        return inst

    @classmethod
    def load(cls, path: str | Path) -> ConformalEstimator:
        """Load a fitted estimator from a JSON file at ``path``."""
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


__all__ = ["ConformalEstimator"]
