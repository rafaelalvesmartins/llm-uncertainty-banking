# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Adapter estimator that delegates to LM-Polygraph (MIT).

LM-Polygraph (Fadeeva et al. 2023, github.com/IINemo/lm-polygraph) ships
~60 uncertainty-estimation methods for whitebox HuggingFace models. This
module wraps that library behind LUB's :class:`Estimator` contract so
any of those methods can be selected by name from a LUB pipeline without
LUB having to reimplement the underlying algorithms.

The adapter is deliberately *thin*:

1. It accepts only :class:`~lub.wrappers.hf.HFBackend` — LM-Polygraph
   requires whitebox access to a PyTorch model and a tokenizer.
2. It imports ``lm_polygraph`` lazily so the optional dependency never
   runs at import time. Install with
   ``pip install llm-uncertainty-banking[lmpolygraph]``.
3. It maps LM-Polygraph's raw ``uncertainty`` scalar (higher = more
   uncertain, unbounded above) into a rough ``confidence`` in
   ``[0, 1]`` via ``exp(-|raw|)``. This is a placeholder monotone
   transform, not a calibration. Users running in production should
   fit a :class:`~lub.calibration.normalizers.Normalizer` on a
   held-out calibration set and apply it to ``raw_scores
   ["lmpolygraph_uncertainty"]`` instead of trusting the bare
   exponential mapping.

LM-Polygraph is released under the MIT license; LUB ships the adapter
under Apache-2.0 without bundling any LM-Polygraph source. The
``lm-polygraph`` package, when installed, retains its own license and
notices.
"""

from __future__ import annotations

import math
from typing import Any

import structlog

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty.base import Estimator

_LOG = structlog.get_logger("lub.uncertainty.lmpolygraph")

_MISSING_MSG = (
    "LMPolygraphEstimator requires the 'lm-polygraph' package. "
    "Install with: pip install 'llm-uncertainty-banking[lmpolygraph]'"
)


def _raw_to_confidence(raw: float) -> float:
    """Map an LM-Polygraph raw uncertainty scalar to a rough confidence.

    LM-Polygraph returns an unbounded "uncertainty" score where higher
    means more uncertain. We use ``exp(-|raw|)`` as a smooth, monotone
    transform into ``[0, 1]``. This is not a calibration — it is only
    meant to satisfy the :class:`UncertaintyResult` invariant that
    ``confidence`` lives in ``[0, 1]``. Pair with a fitted
    :class:`~lub.calibration.normalizers.Normalizer` for real
    calibration.
    """
    value = abs(float(raw))
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return float(max(0.0, min(1.0, math.exp(-value))))


class LMPolygraphEstimator(Estimator):
    """Estimator that delegates scoring to LM-Polygraph by method name.

    Parameters
    ----------
    method:
        Name of an LM-Polygraph estimator (e.g. ``"MaximumSequenceProbability"``,
        ``"SemanticEntropy"``, ``"Mahalanobis"``, ``"PTrue"``,
        ``"LexicalSimilarity"``). See LM-Polygraph's
        ``utils/factory_estimator.py`` for the full registry.
    refusal_threshold:
        Forwarded to :class:`UncertaintyResult.should_refuse` as
        ``confidence < refusal_threshold``. Defaults to ``0.5``.
    **method_kwargs:
        Extra keyword arguments passed through to LM-Polygraph's
        estimator factory. Per-method — consult LM-Polygraph docs.
    """

    REGISTRY_KEY = "lmpolygraph"

    def __init__(
        self,
        method: str = "MaximumSequenceProbability",
        refusal_threshold: float = 0.5,
        **method_kwargs: Any,
    ) -> None:
        if not method:
            raise ValueError("method name must be a non-empty string")
        self.method = method
        self.refusal_threshold = self._validate_threshold(refusal_threshold)
        self.method_kwargs = dict(method_kwargs)

    def _require_whitebox(self, backend: BackendProto) -> Any:
        if not hasattr(backend, "_load"):
            raise TypeError(
                "LMPolygraphEstimator requires a whitebox backend exposing "
                "_load() (e.g. HFBackend) — other backends do not provide "
                "the PyTorch model and tokenizer that LM-Polygraph needs. "
                f"Got {type(backend).__name__}."
            )
        return backend

    def _build_whitebox(self, backend: Any) -> Any:
        try:
            from lm_polygraph.utils.model import WhiteboxModel
        except ImportError as exc:
            raise ImportError(_MISSING_MSG) from exc
        model, tokenizer, _ = backend._load()
        return WhiteboxModel(
            base_model=model,
            tokenizer=tokenizer,
            model_path=backend.model_id,
        )

    def _build_method(self) -> Any:
        try:
            from lm_polygraph.utils.factory_estimator import FactoryEstimator
        except ImportError as exc:
            raise ImportError(_MISSING_MSG) from exc
        return FactoryEstimator(self.method, **self.method_kwargs)

    def score(
        self,
        backend: BackendProto,
        prompt: str,
        **kwargs: Any,
    ) -> UncertaintyResult:
        """Compute uncertainty score for the given prompt and answer."""
        # Check backend compatibility first so callers using DummyBackend or
        # other non-HF backends get a clear TypeError even when lm-polygraph
        # is not installed.
        hf_backend = self._require_whitebox(backend)

        try:
            from lm_polygraph import estimate_uncertainty
        except ImportError as exc:
            raise ImportError(_MISSING_MSG) from exc

        wb = self._build_whitebox(hf_backend)
        method = self._build_method()
        output = estimate_uncertainty(wb, method, input_text=prompt)

        raw_uncertainty = float(getattr(output, "uncertainty", 0.0))
        answer = str(getattr(output, "generation_text", "") or "")
        confidence = _raw_to_confidence(raw_uncertainty)

        return UncertaintyResult(
            answer=answer,
            confidence=confidence,
            raw_scores={"lmpolygraph_uncertainty": raw_uncertainty},
            samples=[answer] if answer else None,
            should_refuse=confidence < self.refusal_threshold,
        )


__all__ = ["LMPolygraphEstimator"]
