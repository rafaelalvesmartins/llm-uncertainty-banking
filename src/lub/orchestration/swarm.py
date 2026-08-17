# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""DAA-style swarm fusion over multiple uncertainty estimators.

Instead of choosing one UQ method, run several on the same (prompt,
generation) pair and fuse them into a single calibrated confidence.
Two useful outputs fall out:

1. **Fused confidence** — the weighted mean of per-method confidences.
2. **Method disagreement** — the population stddev across methods.
   When the swarm agrees, trust it more. When it splits, escalate.

The ``method_disagreement`` signal is itself a cheap second-order
predictor of correctness that we report as a research contribution in
``planning/11_Ruflo_Synthesis.md``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from lub.types import UncertaintyResult

if TYPE_CHECKING:
    from lub.uncertainty.base import Estimator
    from lub.wrappers.base import ModelBackend

_LOG = structlog.get_logger("lub.orchestration.swarm")


@dataclass(frozen=True)
class SwarmResult:
    """Aggregate of per-estimator scores over one prompt.

    Attributes
    ----------
    fused:
        Synthetic :class:`UncertaintyResult` whose ``confidence`` is
        the weighted mean and whose ``raw_scores`` carry the per-method
        breakdown plus ``method_disagreement``.
    per_method:
        Raw mapping from estimator name to its :class:`UncertaintyResult`.
    """

    fused: UncertaintyResult
    per_method: dict[str, UncertaintyResult]

    def to_dict(self) -> dict[str, Any]:
        """Serialise the swarm result to a JSON-friendly dictionary."""
        return {
            "fused": {
                "answer": self.fused.answer,
                "confidence": float(self.fused.confidence),
                "raw_scores": dict(self.fused.raw_scores),
                "should_refuse": bool(self.fused.should_refuse),
            },
            "per_method": {
                name: {
                    "answer": r.answer,
                    "confidence": float(r.confidence),
                    "raw_scores": dict(r.raw_scores),
                }
                for name, r in self.per_method.items()
            },
        }


class UQSwarm:
    """Run a list of estimators on one backend and fuse the confidences.

    Parameters
    ----------
    backend:
        Any :class:`~lub.wrappers.base.ModelBackend`. Used by each
        estimator for generation. All estimators see the same backend,
        which guarantees they score the *same* completion.
    estimators:
        Mapping of ``name -> Estimator``. Names appear in logs and in
        ``raw_scores`` under ``method_<name>``.
    weights:
        Optional ``name -> float`` map. Missing names default to
        ``1 / n``. Weights are normalised internally.

    Notes
    -----
    The swarm treats each estimator as independent. If two estimators
    compute strongly-correlated signals (e.g. ``perplexity`` and
    ``token_logprob``) the fusion is still well-defined, but the
    disagreement signal will understate true uncertainty; weights are
    the knob to handle that.
    """

    def __init__(
        self,
        backend: ModelBackend,
        estimators: dict[str, Estimator],
        weights: dict[str, float] | None = None,
    ) -> None:
        if not estimators:
            raise ValueError("UQSwarm requires at least one estimator")
        self.backend = backend
        self.estimators = dict(estimators)
        self.weights = self._normalise_weights(weights, list(estimators))

    @staticmethod
    def _normalise_weights(
        weights: dict[str, float] | None,
        names: list[str],
    ) -> dict[str, float]:
        if weights is None:
            uniform = 1.0 / len(names)
            return dict.fromkeys(names, uniform)
        filled = {n: float(weights.get(n, 1.0)) for n in names}
        total = sum(filled.values())
        if total <= 0.0:
            raise ValueError("UQSwarm weights must sum to a positive number")
        return {n: w / total for n, w in filled.items()}

    def answer(self, prompt: str, **kwargs: Any) -> SwarmResult:
        """Score *prompt* with every estimator and fuse the confidences."""
        per_method: dict[str, UncertaintyResult] = {}
        for name, est in self.estimators.items():
            _LOG.debug("swarm.est.start", name=name)
            per_method[name] = est.score(self.backend, prompt, **kwargs)

        confidences = {n: float(r.confidence) for n, r in per_method.items()}
        fused_conf = sum(self.weights[n] * confidences[n] for n in confidences)
        disagreement = _pop_stddev(list(confidences.values()))

        # All estimators see the same generation, so pick any answer. Prefer the
        # one whose estimator has the highest weight — a stable tiebreak.
        leader = max(self.weights, key=self.weights.get)  # type: ignore[arg-type]
        leader_result = per_method[leader]

        raw_scores: dict[str, float] = {
            "swarm_fused": fused_conf,
            "method_disagreement": disagreement,
        }
        for n, r in per_method.items():
            raw_scores[f"method_{n}"] = float(r.confidence)

        fused = UncertaintyResult(
            answer=leader_result.answer,
            confidence=max(0.0, min(1.0, fused_conf)),
            raw_scores=raw_scores,
            samples=leader_result.samples,
            should_refuse=leader_result.should_refuse,
            diagnostics={"swarm_leader": leader, "swarm_weights": dict(self.weights)},
        )
        _LOG.info(
            "swarm.fused",
            n=len(per_method),
            fused=f"{fused_conf:.4f}",
            disagreement=f"{disagreement:.4f}",
        )
        return SwarmResult(fused=fused, per_method=per_method)


def _pop_stddev(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(var)


__all__ = ["SwarmResult", "UQSwarm"]
