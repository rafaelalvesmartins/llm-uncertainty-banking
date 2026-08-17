# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Abstract base classes for L4 benchmark datasets.

Every concrete dataset yields a stream of :class:`Example` records so that
the benchmark runner can consume datasets of any size without materializing
them in memory. The ``hash`` method gives a reproducibility-grade digest
over example IDs that is stored alongside benchmark results.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar, NamedTuple


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield ``(line_no, record)`` for every non-blank, non-comment line.

    Used by dataset loaders that support a local-JSONL fallback. Blank
    lines and ``#``-prefixed comments are silently skipped; malformed
    JSON raises :class:`ValueError` with the source line number.
    """
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                yield line_no, json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON ({exc})") from exc


_LAZY_REGISTRY: dict[str, str] = {
    "br_regulatory": "lub.benchmarks.br_regulatory",
    "finqa": "lub.benchmarks.finqa",
    "convfinqa": "lub.benchmarks.convfinqa",
    "tatqa": "lub.benchmarks.tatqa",
    "german_credit": "lub.benchmarks.credit_scoring",
    "australian_credit": "lub.benchmarks.credit_scoring",
    "fpb": "lub.benchmarks.financial_sentiment",
    "fiqa_sa": "lub.benchmarks.financial_sentiment",
}


class Example(NamedTuple):
    """A single QA example consumed by the benchmark runner."""

    id: str
    question: str
    gold_answer: str
    metadata: dict[str, Any]


class Dataset(ABC):
    """Abstract contract for a benchmark dataset.

    Concrete subclasses **auto-register** on import via
    ``__init_subclass__``, mirroring the :class:`~lub.uncertainty.base.Estimator`
    and :class:`~lub.wrappers.base.ModelBackend` registry pattern. The CLI
    resolves datasets by ``REGISTRY_KEY`` instead of a hand-maintained dict.
    """

    REGISTRY_KEY: ClassVar[str] = ""
    _registry: ClassVar[dict[str, type[Dataset]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "REGISTRY_KEY" in cls.__dict__ and cls.REGISTRY_KEY:
            Dataset._registry[cls.REGISTRY_KEY] = cls

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable short identifier used in benchmark records (e.g. ``finqa``)."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Dataset version string (upstream release tag or local rev)."""

    @abstractmethod
    def load(self) -> Iterator[Example]:
        """Yield :class:`Example` records. Implementations may be lazy."""

    def validate(self, limit: int | None = 5) -> list[str]:
        """Spot-check the first *limit* examples for schema problems.

        Returns a list of human-readable warnings. An empty list means
        "no problems detected." Called by :class:`BenchmarkRunner` at
        construction time so bad data surfaces immediately rather than
        midway through a long run.

        Subclasses may override to add domain-specific checks (e.g.
        "gold_answer must be numeric for FinQA").
        """
        warnings: list[str] = []
        for i, ex in enumerate(self.load()):
            if limit is not None and i >= limit:
                break
            if not ex.question.strip():
                warnings.append(f"example {ex.id!r}: question is blank")
            if not ex.gold_answer.strip():
                warnings.append(f"example {ex.id!r}: gold_answer is blank")
        return warnings

    @classmethod
    def get_dataset_cls(cls, key: str) -> type[Dataset]:
        """Look up a dataset class by ``REGISTRY_KEY``.

        Falls back to :data:`_LAZY_REGISTRY` if the key is not yet in
        the live registry, importing the module on demand.
        """
        if key not in cls._registry:
            mod_path = _LAZY_REGISTRY.get(key)
            if mod_path:
                import importlib

                importlib.import_module(mod_path)
        try:
            return cls._registry[key]
        except KeyError as exc:
            known = sorted(set(cls._registry) | set(_LAZY_REGISTRY))
            raise ValueError(f"unknown dataset {key!r}; choose from {known}") from exc

    @classmethod
    def list_datasets(cls) -> list[str]:
        """Return all known dataset keys, sorted.

        Includes keys from both the live registry (already-imported datasets)
        and the lazy registry (datasets that can be imported on demand).
        """
        return sorted(set(cls._registry) | set(_LAZY_REGISTRY))

    def hash(self) -> str:
        """Return the sha256 of concatenated example IDs, hex-encoded.

        This walks the **full** dataset and may be expensive. The benchmark
        runner does NOT use this method — it computes a hash incrementally
        over only the examples actually scored (``limit``-aware), so
        ``BenchmarkResult.dataset_hash`` and ``Dataset.hash()`` diverge
        when ``limit`` is set. Use this method only for whole-dataset
        provenance outside of a benchmark run.
        """
        hasher = hashlib.sha256()
        for example in self.load():
            hasher.update(example.id.encode("utf-8"))
            hasher.update(b"\n")
        return hasher.hexdigest()


__all__ = ["Dataset", "Example", "iter_jsonl"]
