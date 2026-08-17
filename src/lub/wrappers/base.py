# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Abstract base class for L1 model backends.

Every concrete backend (HuggingFace, OpenAI, Anthropic, vLLM, Dummy)
implements this contract. Higher layers (uncertainty estimators, pipeline)
depend only on this interface, never on concrete backends.

Whitebox vs blackbox
--------------------

The LLM uncertainty literature (Fadeeva et al. 2023, Lin et al. 2023,
LM-Polygraph) commonly splits model backends into two families:

- **Whitebox** - backends that expose per-token log-probabilities and
  usually hidden-state embeddings. Information-based estimators
  (token log-probability, perplexity, semantic entropy, p(True)\'s
  whitebox path) and density-based estimators (Mahalanobis, EigenScore
  over embeddings) run here.
- **Blackbox** - backends that only return generated text. Diversity-
  based estimators (self-consistency, semantic entropy with a local
  similarity proxy, p(True)\'s blackbox fallback) are the portable
  option on these.

``ModelBackend`` unifies both. A concrete backend implementing only
:meth:`generate` is de facto *blackbox*; one that additionally supports
:meth:`logprobs` and :meth:`embed` is *whitebox*. Backends that cannot
support a given method should raise :class:`NotImplementedError` with a
helpful message - estimators are expected to catch that exception and
fall back to a blackbox path where possible (see
``lub.uncertainty.p_true`` for an example).
"""

from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from enum import Flag, auto
from typing import Any, ClassVar

import numpy as np

from lub.types import Generation, TokenLogProbs

# Wrapper modules that do NOT register a backend (no concrete REGISTRY_KEY).
# Skipped during pkgutil-based discovery so we never import them speculatively.
_NON_BACKEND_MODULES: frozenset[str] = frozenset({"base", "api_base"})


class BackendCapability(Flag):
    """Declarative flag for what a :class:`ModelBackend` can do.

    Every backend implements :meth:`~ModelBackend.generate`; the
    optional methods (:meth:`~ModelBackend.logprobs`,
    :meth:`~ModelBackend.embed`) may raise :class:`NotImplementedError`
    for backends whose underlying provider does not expose them.

    Estimators that need a particular capability declare it via
    :attr:`~lub.uncertainty.base.Estimator.REQUIRES_CAPABILITIES`. The
    pipeline / runner can then check for compatibility *before*
    invoking ``score()`` instead of catching :class:`NotImplementedError`
    at the bottom of the call stack -- yielding a better error message
    and an explicit failure mode for the SR-11-7 audit log.

    Use bitwise composition::

        CAPABILITIES = BackendCapability.GENERATE | BackendCapability.LOGPROBS
    """

    GENERATE = auto()
    LOGPROBS = auto()
    EMBED = auto()

    @classmethod
    def all_capabilities(cls) -> BackendCapability:
        """Return the union of every defined capability."""
        result = cls(0)
        for member in cls:
            result |= member
        return result


# Optional override slot for tests / non-package backends.
# Maps registry key to module dotted path. The default discovery path uses
# ``pkgutil.iter_modules`` over this package, so production code does NOT
# need to maintain a parallel dict here. Tests that ship an out-of-tree
# backend may inject ``key -> "pkg.module"`` entries to make
# :func:`get_backend_cls` import them on first miss.
_LAZY_REGISTRY: dict[str, str] = {}


def _discover_wrapper_module_names() -> list[str]:
    """Return wrapper submodule names that may register a backend.

    Uses :func:`pkgutil.iter_modules` over this package's ``__path__``;
    excludes the ABC/helper modules in :data:`_NON_BACKEND_MODULES`. No
    module is imported here -- discovery is purely a directory listing.
    """
    import lub.wrappers as _pkg

    return [
        info.name
        for info in pkgutil.iter_modules(_pkg.__path__)
        if info.name not in _NON_BACKEND_MODULES
    ]


class ModelBackend(ABC):
    """Abstract contract for a text-generation model backend.

    Concrete subclasses auto-register on import: ``__init_subclass__``
    inserts them into :attr:`_registry` keyed by ``REGISTRY_KEY``. Adding
    a backend is then one file (the wrapper) - no parallel dicts to touch,
    because :meth:`resolve_class_name` reads the live registry directly.
    """

    REGISTRY_KEY: ClassVar[str] = ""
    """Stable short identifier used by :meth:`UncertaintyPipeline.from_dict`
    to rebuild a pipeline from a persisted :class:`BenchmarkResult` without
    round-tripping the class name. Subclasses must set this."""

    CAPABILITIES: ClassVar[BackendCapability] = BackendCapability.GENERATE
    """Declares which methods this backend supports without raising
    :class:`NotImplementedError`. Default is just :attr:`BackendCapability.GENERATE`;
    subclasses should override to claim :attr:`~BackendCapability.LOGPROBS`
    and / or :attr:`~BackendCapability.EMBED` when their underlying
    provider exposes them. Read by callers via :meth:`has_capability`."""

    _registry: ClassVar[dict[str, type[ModelBackend]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Only register when REGISTRY_KEY is declared directly on the
        # subclass, not inherited. Otherwise a test mock that subclasses
        # e.g. DummyBackend would inherit "dummy" as its REGISTRY_KEY
        # and silently overwrite the real DummyBackend registration via
        # last-subclass-wins semantics.
        if "REGISTRY_KEY" in cls.__dict__ and cls.REGISTRY_KEY:
            existing = ModelBackend._registry.get(cls.REGISTRY_KEY)
            if existing is not None and existing is not cls:
                import warnings

                warnings.warn(
                    f"Backend registry key {cls.REGISTRY_KEY!r} was "
                    f"registered by {existing.__name__}, now overwritten "
                    f"by {cls.__name__}",
                    stacklevel=2,
                )
            ModelBackend._registry[cls.REGISTRY_KEY] = cls

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    @property
    def name(self) -> str:
        """Stable identifier used in logs and benchmark records."""
        return f"{type(self).__name__}:{self.model_id}"

    @abstractmethod
    def generate(
        self,
        prompt: str,
        n_samples: int = 1,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> list[Generation]:
        """Return ``n_samples`` completions for ``prompt``."""

    @abstractmethod
    def logprobs(self, prompt: str, completion: str) -> TokenLogProbs:
        """Return token-level log-probabilities of ``completion`` given ``prompt``."""

    @abstractmethod
    def embed(self, text: str) -> np.ndarray[Any, Any]:
        """Return a fixed-dimensional dense embedding of ``text``."""

    def has_capability(self, capability: BackendCapability) -> bool:
        """Return ``True`` iff this backend declares ``capability`` (and
        all of its bitwise components, when called with a composite flag).

        Mirrors the semantics of :class:`enum.Flag` membership check:

            >>> backend.has_capability(
            ...     BackendCapability.GENERATE | BackendCapability.LOGPROBS
            ... )

        is ``True`` only when the backend supports BOTH.
        """
        return (self.CAPABILITIES & capability) == capability

    @classmethod
    def resolve_class_name(cls, class_name: str) -> str:
        """Map a legacy class name to its ``REGISTRY_KEY``.

        Inspects the live registry instead of a hand-maintained dict.
        Falls back to ``class_name.lower()`` when the class name is not
        found, preserving backward compatibility with unknown backends.
        """
        for key, backend_cls in cls._registry.items():
            if backend_cls.__name__ == class_name:
                return key
        return class_name.lower()


def get_backend_cls(key: str) -> type[ModelBackend]:
    """Look up a backend class by its ``REGISTRY_KEY``.

    If the backend is not yet in the registry (e.g., because the module
    hasn\'t been imported), attempts a lazy import from the known module path.

    Parameters
    ----------
    key : str
        The registry key for the backend.

    Returns
    -------
    type[ModelBackend]
        The backend class.

    Raises
    ------
    ValueError
        If the registry key is unknown.
    """
    # Fast path: already-registered backend.
    if key in ModelBackend._registry:
        return ModelBackend._registry[key]

    # Test-injected override takes precedence over package discovery.
    override = _LAZY_REGISTRY.get(key)
    if override:
        importlib.import_module(override)
    else:
        # Discover wrapper submodules; prefer the same-named module if any
        # (the convention in this package), otherwise import each candidate
        # until ``__init_subclass__`` populates the registry for ``key``.
        discovered = _discover_wrapper_module_names()
        if key in discovered:
            importlib.import_module(f"lub.wrappers.{key}")
        else:
            for name in discovered:
                importlib.import_module(f"lub.wrappers.{name}")
                if key in ModelBackend._registry:
                    break

    try:
        return ModelBackend._registry[key]
    except KeyError as exc:
        known = sorted(set(ModelBackend._registry) | set(_discover_wrapper_module_names()))
        raise ValueError(f"unknown backend {key!r}; choose from {known}") from exc


def list_backends() -> list[str]:
    """Return all known backend ``REGISTRY_KEY`` values, sorted.

    Includes keys from the live registry (already-imported backends), any
    test-injected overrides in :data:`_LAZY_REGISTRY`, and wrapper
    submodules discovered via :func:`pkgutil.iter_modules` (which are not
    imported here -- discovery is purely a directory listing, so listing
    is safe on hosts where e.g. the ``vllm`` extra is not installed).
    """
    return sorted(
        set(ModelBackend._registry) | set(_LAZY_REGISTRY) | set(_discover_wrapper_module_names())
    )


__all__ = ["BackendCapability", "ModelBackend", "get_backend_cls", "list_backends"]
