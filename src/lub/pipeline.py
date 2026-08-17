# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""High-level entry point that ties a backend + estimator together.

Concrete estimators and backends self-register on import via their
``__init_subclass__`` hooks; this module relies on that rather than
hand-maintaining parallel dicts. The registry bootstrap (importing
:mod:`lub.uncertainty` and :mod:`lub.wrappers`) happens in the top-level
:mod:`lub` package ``__init__``, so any code path that reaches this
module has already populated the registries.
"""

from __future__ import annotations

from typing import Any

import structlog

from lub.rails import RailSet
from lub.types import UncertaintyResult
from lub.uncertainty.base import Estimator, get_estimator_cls
from lub.wrappers.base import ModelBackend, get_backend_cls

_LOG = structlog.get_logger("lub.pipeline")


def _build_backend(backend: str, model: str) -> ModelBackend:
    cls = get_backend_cls(backend)
    return cls(model_id=model)


def _build_estimator(name: str, **kwargs: Any) -> Estimator:
    cls = get_estimator_cls(name)
    return cls(**kwargs)


def _estimator_name(estimator: Estimator) -> str:
    return type(estimator).REGISTRY_KEY or type(estimator).__name__


class UncertaintyPipeline:
    """Bind a :class:`ModelBackend` to an :class:`Estimator`.

    The pipeline is the public, user-facing facade. It enforces a global
    ``refusal_threshold`` on top of whatever the estimator returns, runs
    single or batched prompts, and can be round-tripped through
    :meth:`to_dict` / :meth:`from_dict` for reproducible configuration.
    """

    def __init__(
        self,
        backend: ModelBackend,
        estimator: Estimator,
        refusal_threshold: float = 0.5,
        rails: RailSet | None = None,
    ) -> None:
        # Delegate validation to the shared helper so the pipeline and
        # every estimator emit the same error message for the same
        # invariant.
        self.refusal_threshold = Estimator._validate_threshold(
            refusal_threshold, name="refusal_threshold"
        )
        self.backend = backend
        self.estimator = estimator
        self.rails = rails

    @classmethod
    def from_pretrained(
        cls,
        model: str,
        backend: str = "hf",
        estimator: str = "self_consistency",
        refusal_threshold: float = 0.5,
        rails: RailSet | None = None,
        **estimator_kwargs: Any,
    ) -> UncertaintyPipeline:
        """Construct a pipeline from a pretrained model identifier.

        Args:
            model: Model name or path to load.
            backend: Inference backend to use (e.g., "hf").
            estimator: Uncertainty estimator to attach to the pipeline.

        Returns:
            A configured pipeline instance ready for inference.
        """
        be = _build_backend(backend, model)
        est = _build_estimator(estimator, **estimator_kwargs)
        return cls(
            backend=be,
            estimator=est,
            refusal_threshold=refusal_threshold,
            rails=rails,
        )

    def answer(self, prompt: str, **kwargs: Any) -> UncertaintyResult:
        """Score one prompt and return an :class:`UncertaintyResult`.

        Evaluation order is intentional:

        1. ``rails.apply_input(prompt)`` - input-side policies (PII
           redaction, jailbreak detection) can rewrite or reject the
           prompt before it reaches the estimator.
        2. ``estimator.score(backend, effective_prompt, **kwargs)`` -
           estimator kwargs flow through unchanged so callers can
           override per-call generation knobs (e.g. ``n_samples``,
           ``temperature``).
        3. Apply the pipeline's global ``refusal_threshold`` on top of
           whatever ``should_refuse`` the estimator returned. The
           threshold can only *raise* the refusal bit, never clear it.
        4. ``rails.apply_output(result)`` - output-side policies
           (hallucination guards, tone filters) can override the final
           answer, confidence, or refusal bit.
        """
        est_name = _estimator_name(self.estimator)
        _LOG.debug(
            "pipeline.answer.start",
            estimator=est_name,
            backend=self.backend.model_id,
            prompt_len=len(prompt),
        )
        effective_prompt = self.rails.apply_input(prompt) if self.rails else prompt
        result = self.estimator.score(self.backend, effective_prompt, **kwargs)
        if result.confidence < self.refusal_threshold:
            result = result.with_should_refuse(True)
        if self.rails:
            result = self.rails.apply_output(result)
        _LOG.debug(
            "pipeline.answer.done",
            estimator=est_name,
            confidence=f"{result.confidence:.4f}",
            should_refuse=result.should_refuse,
        )
        return result

    def batch_answer(
        self,
        prompts: list[str],
        **kwargs: Any,
    ) -> list[UncertaintyResult]:
        """Score a batch of prompts sequentially.

        Thin convenience over :meth:`answer` that forwards ``**kwargs``
        unchanged to every call. Execution is serial - there is no
        cross-prompt state so callers can parallelize externally
        (``concurrent.futures``) if the backend supports it.
        """
        return [self.answer(p, **kwargs) for p in prompts]

    def to_dict(self) -> dict[str, Any]:
        """Serialize pipeline configuration (not fitted state) to a dict.

        ``backend`` is the stable ``REGISTRY_KEY`` of the backend class,
        not the raw class name, so renames and refactors don\'t break
        :meth:`from_dict` round-trip. ``rails`` are NOT serialized - rail
        sets are runtime objects that can hold callbacks, regex objects,
        or third-party clients - so a round-tripped pipeline loses its
        rails. ``rails_configured`` is emitted as a marker so
        :meth:`from_dict` can warn.
        """
        backend_cls = type(self.backend)
        backend_key = backend_cls.REGISTRY_KEY or ModelBackend.resolve_class_name(
            backend_cls.__name__
        )
        return {
            "backend": backend_key,
            "model": self.backend.model_id,
            "estimator": _estimator_name(self.estimator),
            "refusal_threshold": self.refusal_threshold,
            "rails_configured": self.rails is not None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UncertaintyPipeline:
        """Rebuild a pipeline from :meth:`to_dict` output.

        Accepts both the new stable ``REGISTRY_KEY`` form
        (``"dummy"``, ``"hf"``, ...) and the legacy class-name form
        (``"DummyBackend"``, ``"HFBackend"``, ...) so that older persisted
        ``BenchmarkResult`` records remain loadable.

        If the source pipeline had rails attached, they are not restored
        (see :meth:`to_dict`); a structlog warning is emitted so callers
        notice the gap instead of discovering it at runtime.
        """
        backend_value = data["backend"]
        if backend_value in ModelBackend._registry:
            backend_key = backend_value
        else:
            backend_key = ModelBackend.resolve_class_name(backend_value)
        if data.get("rails_configured"):
            _LOG.warning(
                "pipeline.from_dict.rails_dropped",
                reason="rails are runtime-only and not serialized",
                action="attach rails manually after from_dict() if required",
            )
        return cls.from_pretrained(
            model=data["model"],
            backend=backend_key,
            estimator=data["estimator"],
            refusal_threshold=float(data.get("refusal_threshold", 0.5)),
        )


__all__ = ["UncertaintyPipeline"]
