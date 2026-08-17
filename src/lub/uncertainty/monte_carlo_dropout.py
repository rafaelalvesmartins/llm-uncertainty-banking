# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Monte Carlo dropout uncertainty estimator.

Implements Gal & Ghahramani (2016), "Dropout as a Bayesian Approximation:
Representing Model Uncertainty in Deep Learning" (ICML 2016). At inference
time we enable dropout in the forward pass, run ``n_forward_passes``
stochastic generations, and decompose total predictive entropy into
aleatoric (expected entropy) and epistemic (mutual information) parts. We
use the epistemic component, normalized, as an inverse confidence.

Only compatible with :class:`~lub.wrappers.hf.HFBackend` because we need
direct access to the underlying ``nn.Module`` to toggle dropout without
flipping the rest of the model into train mode (which would also affect
BatchNorm statistics).
"""

from __future__ import annotations

import math
from typing import Any

import structlog

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty._math_utils import entropy_from_probs
from lub.uncertainty.base import Estimator

_LOG = structlog.get_logger("lub.uncertainty.monte_carlo_dropout")


def _toggle_dropout(module: Any, enable: bool) -> None:
    """Walk ``module`` and put only dropout layers in train/eval mode."""
    import torch.nn as nn  # lazy to keep torch out of the import graph

    dropout_types: tuple[type, ...] = (nn.Dropout, nn.Dropout2d, nn.Dropout3d)
    for sub in module.modules():
        if isinstance(sub, dropout_types):
            sub.train(mode=enable)  # type: ignore[attr-defined]


class MCDropoutEstimator(Estimator):
    """Monte Carlo dropout estimator (Gal & Ghahramani, 2016)."""

    REGISTRY_KEY = "mc_dropout"

    def __init__(
        self,
        n_forward_passes: int = 20,
        temperature: float = 1.0,
        max_tokens: int = 64,
    ) -> None:
        if n_forward_passes < 2:
            raise ValueError(f"n_forward_passes must be >= 2, got {n_forward_passes}")
        self.n_forward_passes = n_forward_passes
        self.temperature = temperature
        self.max_tokens = max_tokens

    def _require_whitebox(self, backend: BackendProto) -> Any:
        if not hasattr(backend, "_load"):
            raise TypeError(
                "MCDropoutEstimator requires a whitebox backend exposing "
                "_load() (e.g. HFBackend) — other backends do not provide "
                "the nn.Module needed to toggle dropout at inference time. "
                f"Got {type(backend).__name__}."
            )
        model, _, _ = backend._load()
        return model

    @staticmethod
    def _per_position_probs(
        logprobs_per_pass: list[list[float]],
    ) -> tuple[float, float]:
        """Return (predictive entropy H, expected entropy E[H]) in nats.

        Approximation: each pass gives us, for each generated position, the
        log-probability of the token the sampler actually chose. We treat
        that as a point estimate of ``p(y=chosen | x, theta_i)`` and
        average across passes.
        """
        if not logprobs_per_pass:
            return 0.0, 0.0

        nonempty = [p for p in logprobs_per_pass if p]
        if not nonempty:
            return 0.0, 0.0
        min_len = min(len(p) for p in nonempty)
        if min_len == 0:
            return 0.0, 0.0

        predictive_entropy = 0.0
        expected_entropy = 0.0
        n_passes = len(logprobs_per_pass)
        for pos in range(min_len):
            probs = [math.exp(p[pos]) for p in logprobs_per_pass]
            mean_p = sum(probs) / n_passes
            # predictive entropy: entropy of the mean predictive distribution
            # at this position (binary "this token vs not" view).
            predictive_entropy += entropy_from_probs([mean_p])
            # expected entropy: mean over passes of per-pass entropy at this
            # position (again binary "this token vs not").
            per_pass_h = [entropy_from_probs([pr]) for pr in probs]
            expected_entropy += sum(per_pass_h) / n_passes
        # Normalize by sequence length to keep values comparable.
        predictive_entropy /= min_len
        expected_entropy /= min_len
        return predictive_entropy, expected_entropy

    def score(
        self,
        backend: BackendProto,
        prompt: str,
        **kwargs: Any,
    ) -> UncertaintyResult:
        """Compute uncertainty score for the given prompt and answer."""
        model = self._require_whitebox(backend)

        _toggle_dropout(model, enable=True)
        try:
            logprobs_per_pass: list[list[float]] = []
            texts: list[str] = []
            for _ in range(self.n_forward_passes):
                generations = backend.generate(
                    prompt,
                    n_samples=1,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                if not generations:
                    continue
                gen = generations[0]
                texts.append(gen.text)
                logprobs_per_pass.append(list(gen.logprobs) if gen.logprobs is not None else [])
        finally:
            _toggle_dropout(model, enable=False)
            model.eval()

        predictive_entropy, expected_entropy = self._per_position_probs(logprobs_per_pass)
        mutual_information = max(predictive_entropy - expected_entropy, 0.0)
        # ln(2) is a convenient unit-1 cap; for open-vocab decoding MI is
        # usually well under 1 nat, so this normalization is a pragmatic
        # gate rather than a theoretical bound.
        normalized_mi = min(mutual_information / math.log(2), 1.0)
        confidence = 1.0 - normalized_mi

        answer = texts[0] if texts else ""
        raw_scores: dict[str, float] = {
            "predictive_entropy": predictive_entropy,
            "expected_entropy": expected_entropy,
            "mutual_information": mutual_information,
            "n_forward_passes": float(self.n_forward_passes),
        }
        return UncertaintyResult(
            answer=answer,
            confidence=confidence,
            raw_scores=raw_scores,
            samples=texts or None,
            should_refuse=confidence < 0.5,
        )


__all__ = ["MCDropoutEstimator"]
