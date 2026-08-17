# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Abstract base class for L2 uncertainty estimators.

Every concrete estimator consumes a :class:`~lub.wrappers.base.ModelBackend`
and a prompt, and returns an :class:`~lub.types.UncertaintyResult` with a
calibrated-ish confidence in ``[0, 1]`` plus estimator-specific diagnostics.

:class:`Estimator` also publishes small validation and post-processing
helpers used by most concrete estimators — clamping confidence into
``[0, 1]``, raising a uniform error when the backend returned no
generations, etc. Subclasses should call them instead of re-implementing
the same one-liners.
"""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from typing import Any, ClassVar

import structlog

from lub.exceptions import CapabilityError
from lub.protocols import BackendProto
from lub.types import Generation, UncertaintyResult
from lub.wrappers.base import BackendCapability

_LOG = structlog.get_logger("lub.uncertainty.base")

# Lazy registry for estimators not yet imported.
# Maps registry key to module path. Used by get_estimator_cls() as fallback
# when a name is not in the registry yet — this allows code to resolve
# estimators by name without relying on the bootstrap import of __init__.py.
#
# INVARIANT: the key here MUST be the class's ``REGISTRY_KEY``, not the module basename.
# It used to be keyed by module basename, which silently broke every estimator whose class
# registers under a different name — ``monte_carlo_dropout``/``sar``/``verbalized`` were
# advertised by ``list_estimators()`` but ALWAYS raised ValueError on lookup (the lazy import
# fired, the class registered under its real key, and the requested key still wasn't there),
# while the 4 real estimators behind them (``mc_dropout``, ``token_sar``, ``verbalized_1s``,
# ``verbalized_2s``) were unreachable by name from a cold process because no lazy key pointed
# at them. Guarded by tests/unit/test_estimator_base.py::
# test_every_advertised_estimator_resolves_to_itself — keep them in sync when adding one.
_LAZY_REGISTRY: dict[str, str] = {
    "adaptive_conformal": "lub.uncertainty.adaptive_conformal",
    "ccp": "lub.uncertainty.ccp",
    "claim_level": "lub.uncertainty.claim_level",
    "conformal": "lub.uncertainty.conformal",
    "conformal_sampling": "lub.uncertainty.conformal_sampling",
    "eigenscore": "lub.uncertainty.eigenscore",
    "ensemble": "lub.uncertainty.ensemble",
    "epistemic_aleatoric": "lub.uncertainty.epistemic_aleatoric",
    "graph_laplacian": "lub.uncertainty.graph_laplacian",
    "lmpolygraph": "lub.uncertainty.lmpolygraph",
    "mahalanobis": "lub.uncertainty.mahalanobis",
    "mc_dropout": "lub.uncertainty.monte_carlo_dropout",  # class registers as mc_dropout
    "mondrian_conformal": "lub.uncertainty.mondrian_conformal",
    "p_true": "lub.uncertainty.p_true",
    "perplexity": "lub.uncertainty.perplexity",
    "self_certainty": "lub.uncertainty.self_certainty",
    "self_consistency": "lub.uncertainty.self_consistency",
    "semantic_entropy": "lub.uncertainty.semantic_entropy",
    "sentence_sar": "lub.uncertainty.sentence_sar",
    "token_logprob": "lub.uncertainty.token_logprob",
    "token_sar": "lub.uncertainty.sar",  # module is sar.py; class registers as token_sar
    "verbalized_1s": "lub.uncertainty.verbalized",  # verbalized.py ships two classes
    "verbalized_2s": "lub.uncertainty.verbalized",
}


class Estimator(ABC):
    """Abstract contract for an uncertainty estimator.

    Subclasses set ``NAME`` to the stable registry key used by
    :class:`lub.pipeline.UncertaintyPipeline` — the benchmark runner reads
    this when writing :class:`lub.types.BenchmarkResult` so ``lub repro``
    can rebuild the pipeline from the persisted record.

    Concrete subclasses **auto-register** on import: ``__init_subclass__``
    inserts them into :attr:`_registry` keyed by ``REGISTRY_KEY``. This
    collapses "adding an estimator" from 3 file edits (new module +
    uncertainty __init__ + pipeline registry) to 1.
    """

    REGISTRY_KEY: ClassVar[str] = ""

    REQUIRES_CAPABILITIES: ClassVar[BackendCapability] = BackendCapability.GENERATE
    """Declares the minimum :class:`~lub.wrappers.base.BackendCapability`
    set this estimator needs from the underlying backend.

    Default is :attr:`BackendCapability.GENERATE`, which every backend
    supports. Estimators that depend on token log-probabilities should
    declare ``GENERATE | LOGPROBS``; estimators that depend on dense
    embeddings should declare ``GENERATE | EMBED``. Subclasses that
    work with a fallback path (e.g. :class:`PTrueEstimator`, which
    tries ``logprobs`` first and falls back to majority vote) should
    keep the default and check capability membership at the call site
    so the fallback can engage cleanly.

    The helper :meth:`_assert_backend_capabilities` reads this attribute
    and raises :class:`~lub.exceptions.CapabilityError` when the supplied
    backend cannot satisfy it. Estimators that want fail-loud semantics
    should call it at the top of :meth:`score`."""

    _registry: ClassVar[dict[str, type[Estimator]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "REGISTRY_KEY" in cls.__dict__ and cls.REGISTRY_KEY:
            existing = Estimator._registry.get(cls.REGISTRY_KEY)
            if existing is not None and existing is not cls:
                import warnings

                warnings.warn(
                    f"Estimator registry key {cls.REGISTRY_KEY!r} was "
                    f"registered by {existing.__name__}, now overwritten "
                    f"by {cls.__name__}",
                    stacklevel=2,
                )
            Estimator._registry[cls.REGISTRY_KEY] = cls

    @abstractmethod
    def score(
        self,
        backend: BackendProto,
        prompt: str,
        **kwargs: Any,
    ) -> UncertaintyResult:
        """Return an :class:`UncertaintyResult` for ``prompt`` under ``backend``."""

    @staticmethod
    def _validate_threshold(t: float, name: str = "refusal_threshold") -> float:
        if not 0.0 <= t <= 1.0:
            raise ValueError(f"{name} must be in [0, 1], got {t}")
        return float(t)

    @staticmethod
    def _validate_n_samples(n: int, minimum: int = 1) -> int:
        if n < minimum:
            raise ValueError(f"n_samples must be >= {minimum}, got {n}")
        return int(n)

    @staticmethod
    def _validate_temperature(t: float, *, allow_zero: bool = False) -> float:
        lower_ok = t >= 0.0 if allow_zero else t > 0.0
        if not lower_ok:
            msg = ">= 0" if allow_zero else "> 0"
            raise ValueError(f"temperature must be {msg}, got {t}")
        return float(t)

    @staticmethod
    def _clip01(x: float) -> float:
        """Clamp ``x`` into the closed interval ``[0, 1]``."""
        if x < 0.0:
            return 0.0
        if x > 1.0:
            return 1.0
        return float(x)

    @classmethod
    def _require_generations(cls, gens: list[Generation]) -> list[Generation]:
        """Return ``gens`` unchanged, or raise a uniform RuntimeError."""
        if not gens:
            raise RuntimeError(f"{cls.__name__}: backend.generate returned no generations")
        return gens

    @staticmethod
    def _logprobs_or_empty(gen: Generation) -> list[float]:
        """``gen.logprobs`` or an empty list -- never ``None``."""
        return list(gen.logprobs) if gen.logprobs is not None else []

    @classmethod
    def _assert_backend_capabilities(cls, backend: Any) -> None:
        """Raise :class:`CapabilityError` when ``backend`` lacks the
        capabilities declared in :attr:`REQUIRES_CAPABILITIES`.

        Reads ``backend.CAPABILITIES`` (default
        :attr:`BackendCapability.GENERATE` if the backend predates the
        capability flag) and compares against the estimator's
        :attr:`REQUIRES_CAPABILITIES`. Estimators that prefer fail-loud
        semantics should call this at the top of :meth:`score`; those
        with documented blackbox fallback paths should not.

        Args:
            backend: Any object whose class declares
                :attr:`~lub.wrappers.base.ModelBackend.CAPABILITIES`.
                Backends that do not (e.g. test doubles) are treated
                as supporting only :attr:`BackendCapability.GENERATE`.

        Raises:
            CapabilityError: When the backend is missing one or more
                bits required by the estimator.
        """
        backend_caps: BackendCapability = getattr(
            type(backend), "CAPABILITIES", BackendCapability.GENERATE
        )
        missing = cls.REQUIRES_CAPABILITIES & ~backend_caps
        if missing:
            raise CapabilityError(
                f"{cls.__name__} requires backend capabilities "
                f"{cls.REQUIRES_CAPABILITIES.name or cls.REQUIRES_CAPABILITIES!r} "
                f"but backend {type(backend).__name__} only declares "
                f"{backend_caps.name or backend_caps!r}; missing: "
                f"{missing.name or missing!r}",
                context={
                    "estimator": cls.__name__,
                    "backend": type(backend).__name__,
                    "required": str(cls.REQUIRES_CAPABILITIES),
                    "available": str(backend_caps),
                    "missing": str(missing),
                },
            )


def get_estimator_cls(name: str) -> type[Estimator]:
    """Look up an estimator class by its ``REGISTRY_KEY``.

    If the estimator is not yet in the registry (e.g., because the module
    hasn't been imported), attempts a lazy import from the known module path.

    Parameters
    ----------
    name : str
        The registry key for the estimator.

    Returns
    -------
    type[Estimator]
        The estimator class.

    Raises
    ------
    ValueError
        If the registry key is unknown.
    """
    # If not in registry, try lazy import.
    if name not in Estimator._registry:
        mod_path = _LAZY_REGISTRY.get(name)
        if mod_path:
            mod = importlib.import_module(mod_path)
            # If the module was already imported but the registry was
            # cleared (e.g., by NumPy/torch reimport during test runs),
            # re-importing is a no-op.  Force-reload so __init_subclass__
            # re-registers the class.
            if name not in Estimator._registry:
                importlib.reload(mod)

    # Now try to get it
    try:
        return Estimator._registry[name]
    except KeyError as exc:
        known = sorted(set(Estimator._registry) | set(_LAZY_REGISTRY))
        raise ValueError(f"unknown estimator {name!r}; choose from {known}") from exc


def list_estimators() -> list[str]:
    """Return all known estimator ``REGISTRY_KEY`` values, sorted.

    Includes keys from both the live registry (already-imported estimators)
    and the lazy registry (estimators that can be imported on demand).
    """
    return sorted(set(Estimator._registry) | set(_LAZY_REGISTRY))


__all__ = ["Estimator", "get_estimator_cls", "list_estimators"]
