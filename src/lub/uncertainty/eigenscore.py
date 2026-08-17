# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""EigenScore semantic-diversity estimator.

Samples ``n`` generations from the backend, embeds them via
:meth:`ModelBackend.embed`, and computes the spectrum of the centered
kernel (Gram) matrix of those embeddings. A tightly-clustered set of
answers produces a spectrum dominated by a single large eigenvalue
(low diversity, high confidence); a spread-out set produces a flatter
spectrum (high diversity, low confidence).

Unlike semantic entropy, EigenScore does **not** require an NLI model,
only that the backend provides an ``embed`` method. This makes it the
preferred diversity-based estimator for backends that have no
``sentence-transformers`` dependency available.

Reference:
    Lin, Z., Trivedi, S., & Sun, J. (2023). *Generating with Confidence:
    Uncertainty Quantification for Black-box Large Language Models.*
    arXiv:2305.19187.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import structlog

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty.base import Estimator

_LOG = structlog.get_logger("lub.uncertainty.eigenscore")


class EigenScoreEstimator(Estimator):
    """Lin et al. 2023 EigenScore diversity estimator."""

    REGISTRY_KEY = "eigenscore"

    def __init__(
        self,
        n_samples: int = 10,
        temperature: float = 0.7,
        refusal_threshold: float = 0.5,
    ) -> None:
        self.n_samples = self._validate_n_samples(n_samples, minimum=2)
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
        texts = [g.text for g in generations]

        try:
            embeddings = np.stack([backend.embed(t) for t in texts], axis=0)
        except NotImplementedError as exc:
            raise TypeError(
                f"EigenScoreEstimator requires a backend with a working "
                f"embed() method; {type(backend).__name__} does not support "
                f"embeddings. Use HFBackend or OpenAIBackend, or switch to "
                f"a sampling-only estimator like self_consistency or "
                f"semantic_entropy."
            ) from exc
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0.0, 1.0, norms)
        unit = embeddings / norms
        gram = unit @ unit.T
        n = gram.shape[0]
        centering = np.eye(n) - np.ones((n, n)) / n
        centered = centering @ gram @ centering

        # Eigenvalues are real since `centered` is symmetric and sorted
        # ascending by eigvalsh. The rank-(n-1) centering always produces
        # one spurious zero eigenvalue; drop it so the score reflects
        # only the n-1 informative directions.
        eigvals = np.linalg.eigvalsh(centered)[1:]
        eigvals = np.clip(eigvals, a_min=1e-12, a_max=None)

        # EigenScore = - (1/(n-1)) * sum(log(eig)), per Lin et al. 2023 eq. 4.
        # A lower score means a more degenerate spectrum -> more agreement.
        eigen_score = float(-np.mean(np.log(eigvals)))

        # Map to confidence via a bounded monotone transform. When all
        # answers are identical (gram -> J_n), the centered Gram is the
        # zero matrix and every eigenvalue floors at 1e-12, giving
        # eigen_score ~ -log(1e-12) ~ 27.6. We treat that as "maximum
        # confidence". A diverse set gives a smaller eigen_score (less
        # negative log mass), which maps to lower confidence.
        max_score = -math.log(1e-12)
        confidence = max(0.0, min(1.0, eigen_score / max_score))

        # Pick a representative answer: the one closest to the mean embedding.
        mean_emb = unit.mean(axis=0, keepdims=True)
        sims = (unit @ mean_emb.T).ravel()
        best_idx = int(np.argmax(sims))
        answer = texts[best_idx]

        raw_scores: dict[str, float] = {
            "eigen_score": eigen_score,
            "n_samples": float(self.n_samples),
            "top_eigenvalue": float(eigvals[-1]),
            "mean_similarity": float(sims.mean()),
        }
        return UncertaintyResult(
            answer=answer,
            confidence=confidence,
            raw_scores=raw_scores,
            samples=texts,
            should_refuse=confidence < self.refusal_threshold,
        )


__all__ = ["EigenScoreEstimator"]
