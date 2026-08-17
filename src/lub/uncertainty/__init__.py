# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""L2 uncertainty estimators.

Estimator classes are lazy-loaded on first access via ``__getattr__``.
This avoids importing all 22 estimator modules (and their transitive
dependencies) when only one is needed — improving CLI startup time by
30-50%.  The base class :class:`Estimator` is always eagerly available
because downstream code (``pipeline``, ``guard``) needs the ABC and
registry helpers at import time.
"""

from lub.uncertainty.base import Estimator

_LAZY_MAP: dict[str, tuple[str, str]] = {
    "AdaptiveConformalEstimator": (
        "lub.uncertainty.adaptive_conformal",
        "AdaptiveConformalEstimator",
    ),
    "CCPEstimator": ("lub.uncertainty.ccp", "CCPEstimator"),
    "ClaimLevelEstimator": ("lub.uncertainty.claim_level", "ClaimLevelEstimator"),
    "ConformalEstimator": ("lub.uncertainty.conformal", "ConformalEstimator"),
    "ConformalSamplingEstimator": (
        "lub.uncertainty.conformal_sampling",
        "ConformalSamplingEstimator",
    ),
    "EigenScoreEstimator": ("lub.uncertainty.eigenscore", "EigenScoreEstimator"),
    "EnsembleEstimator": ("lub.uncertainty.ensemble", "EnsembleEstimator"),
    "EpistemicAleatoricEstimator": (
        "lub.uncertainty.epistemic_aleatoric",
        "EpistemicAleatoricEstimator",
    ),
    "GraphLaplacianEstimator": ("lub.uncertainty.graph_laplacian", "GraphLaplacianEstimator"),
    "LMPolygraphEstimator": ("lub.uncertainty.lmpolygraph", "LMPolygraphEstimator"),
    "MahalanobisEstimator": ("lub.uncertainty.mahalanobis", "MahalanobisEstimator"),
    "MCDropoutEstimator": ("lub.uncertainty.monte_carlo_dropout", "MCDropoutEstimator"),
    "MondrianConformalEstimator": (
        "lub.uncertainty.mondrian_conformal",
        "MondrianConformalEstimator",
    ),
    "PTrueEstimator": ("lub.uncertainty.p_true", "PTrueEstimator"),
    "PerplexityEstimator": ("lub.uncertainty.perplexity", "PerplexityEstimator"),
    "SelfCertaintyEstimator": ("lub.uncertainty.self_certainty", "SelfCertaintyEstimator"),
    "SelfConsistencyEstimator": ("lub.uncertainty.self_consistency", "SelfConsistencyEstimator"),
    "SemanticEntropyEstimator": ("lub.uncertainty.semantic_entropy", "SemanticEntropyEstimator"),
    "SentenceSAREstimator": ("lub.uncertainty.sentence_sar", "SentenceSAREstimator"),
    "TokenLogprobEstimator": ("lub.uncertainty.token_logprob", "TokenLogprobEstimator"),
    "TokenSAREstimator": ("lub.uncertainty.sar", "TokenSAREstimator"),
    "VerbalizedOneShot": ("lub.uncertainty.verbalized", "VerbalizedOneShot"),
    "VerbalizedTwoShot": ("lub.uncertainty.verbalized", "VerbalizedTwoShot"),
}


def __getattr__(name: str) -> object:
    if name in _LAZY_MAP:
        module_path, class_name = _LAZY_MAP[name]
        import importlib

        mod = importlib.import_module(module_path)
        return getattr(mod, class_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AdaptiveConformalEstimator",
    "CCPEstimator",
    "ClaimLevelEstimator",
    "ConformalEstimator",
    "ConformalSamplingEstimator",
    "EigenScoreEstimator",
    "EnsembleEstimator",
    "EpistemicAleatoricEstimator",
    "Estimator",
    "GraphLaplacianEstimator",
    "LMPolygraphEstimator",
    "MahalanobisEstimator",
    "MCDropoutEstimator",
    "MondrianConformalEstimator",
    "PTrueEstimator",
    "PerplexityEstimator",
    "SelfCertaintyEstimator",
    "SelfConsistencyEstimator",
    "SentenceSAREstimator",
    "SemanticEntropyEstimator",
    "TokenLogprobEstimator",
    "TokenSAREstimator",
    "VerbalizedOneShot",
    "VerbalizedTwoShot",
]
