# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Graph-Laplacian blackbox uncertainty estimator.

Implements the spectral-diversity family from Lin, Trivedi & Sun (2024,
TMLR, arXiv:2305.19187). Given ``n`` sampled generations, build a
pairwise semantic-similarity graph (using the backend's ``embed``
method or, as a fallback, simple Jaccard token overlap) and extract
uncertainty from its Laplacian spectrum:

- **NumSemSets** — number of connected components at a given similarity
  threshold (analogous to the number of semantic clusters in
  :class:`~lub.uncertainty.semantic_entropy.SemanticEntropyEstimator`).
- **Degree(W)** — mean node degree of the weighted similarity graph.
  High degree = tight answer cluster = low uncertainty.
- **EigV(W)** — smallest non-trivial eigenvalue of the unnormalized
  graph Laplacian (Fiedler value). A large Fiedler value indicates a
  well-connected graph (low diversity → low uncertainty).

All three measures are combined into a single confidence score via a
weighted average controlled by ``weights``.

Reference:
    Lin, Z., Trivedi, S., & Sun, J. (2024). *Generating with Confidence:
    Uncertainty Quantification for Black-box Large Language Models.*
    TMLR. arXiv:2305.19187.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import structlog
from numpy.typing import NDArray

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty.base import Estimator
from lub.wrappers.base import BackendCapability

_LOG = structlog.get_logger("lub.uncertainty.graph_laplacian")


def _jaccard(a: str, b: str) -> float:
    """Token-level Jaccard similarity as an embedding-free fallback."""
    sa = set(a.lower().split())
    sb = set(b.lower().split())
    if not sa and not sb:
        return 1.0
    union = sa | sb
    if not union:
        return 1.0
    return len(sa & sb) / len(union)


class GraphLaplacianEstimator(Estimator):
    """Spectral-diversity UQ from a generation similarity graph (Lin+ 2024)."""

    REGISTRY_KEY = "graph_laplacian"
    REQUIRES_CAPABILITIES = BackendCapability.GENERATE | BackendCapability.EMBED

    def __init__(
        self,
        n_samples: int = 10,
        temperature: float = 0.7,
        similarity_threshold: float = 0.5,
        refusal_threshold: float = 0.5,
        max_tokens: int = 256,
    ) -> None:
        self.n_samples = self._validate_n_samples(n_samples, minimum=2)
        self.temperature = self._validate_temperature(temperature)
        self.similarity_threshold = self._validate_threshold(
            similarity_threshold, name="similarity_threshold"
        )
        self.refusal_threshold = self._validate_threshold(refusal_threshold)
        self.max_tokens = max_tokens

    def _similarity_matrix(self, texts: list[str], backend: BackendProto) -> NDArray[np.float64]:
        """Build pairwise similarity matrix. Prefer embeddings; fallback to Jaccard."""
        n = len(texts)
        try:
            embs = np.stack([backend.embed(t) for t in texts], axis=0)
            norms = np.linalg.norm(embs, axis=1, keepdims=True)
            norms = np.where(norms == 0.0, 1.0, norms)
            unit = embs / norms
            W = unit @ unit.T
            np.fill_diagonal(W, 0.0)
            result: NDArray[np.float64] = np.clip(W, 0.0, 1.0)
            return result
        except (NotImplementedError, TypeError):
            sim: NDArray[np.float64] = np.zeros((n, n), dtype=np.float64)
            for i in range(n):
                for j in range(i + 1, n):
                    s = _jaccard(texts[i], texts[j])
                    sim[i, j] = s
                    sim[j, i] = s
            return sim

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
        n = len(texts)
        W = self._similarity_matrix(texts, backend)

        # --- NumSemSets: connected components at threshold ---
        adj = (self.similarity_threshold <= W).astype(int)
        visited = [False] * n
        n_components = 0
        for start in range(n):
            if visited[start]:
                continue
            n_components += 1
            stack = [start]
            while stack:
                node = stack.pop()
                if visited[node]:
                    continue
                visited[node] = True
                for neighbor in range(n):
                    if adj[node, neighbor] and not visited[neighbor]:
                        stack.append(neighbor)

        # --- Degree(W): mean weighted degree ---
        degrees = W.sum(axis=1)
        mean_degree = float(degrees.mean())
        max_possible_degree = float(n - 1)

        # --- EigV(W): Fiedler value of the graph Laplacian ---
        D = np.diag(degrees)
        L = D - W
        eigvals = np.linalg.eigvalsh(L)
        eigvals = np.sort(eigvals)
        fiedler = float(eigvals[1]) if n > 1 else 0.0

        # Confidence: combine signals. High degree + high Fiedler +
        # few components → tight cluster → high confidence.
        degree_score = mean_degree / max(max_possible_degree, 1.0)
        component_score = 1.0 / max(n_components, 1)
        fiedler_score = min(fiedler / max(math.log(n), 1.0), 1.0)
        confidence = self._clip01(0.4 * degree_score + 0.3 * component_score + 0.3 * fiedler_score)

        majority = max(set(texts), key=lambda t: texts.count(t))

        return UncertaintyResult(
            answer=majority,
            confidence=confidence,
            raw_scores={
                "num_sem_sets": float(n_components),
                "mean_degree": mean_degree,
                "fiedler_value": fiedler,
                "degree_score": degree_score,
                "component_score": component_score,
                "fiedler_score": fiedler_score,
                "n_samples": float(n),
            },
            samples=texts,
            should_refuse=confidence < self.refusal_threshold,
        )


__all__ = ["GraphLaplacianEstimator"]
