# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""lub.benchmarks.protocol -- explicit Protocol surface for benchmark plug-ins.

Introduced in spec 30 (pass 30) as part of the generic-first architecture
target. The :class:`Dataset` ABC in :mod:`lub.benchmarks.base` already gives
a concrete inheritance hook with auto-registration; this module adds the
**duck-typed equivalent** so that external domain packages (e.g. a future
``lub.domains.banking.benchmarks.finqa``, or a third-party
``acme_healthcare.benchmarks.medqa``) can supply benchmark datasets
*without inheriting from* :class:`Dataset` if they prefer composition.

The intent is to make the v0.3+ migration path documented and testable
without breaking v0.1: the existing :class:`Dataset` subclasses continue
to be the canonical implementation surface; this Protocol is the
forward-compatible escape hatch.

See ``planning/30_Generic_Architecture_Spec_2026-04-25.md`` §4 for the
v0.1-vs-v0.3+ split.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from lub.benchmarks.base import Dataset, Example

__all__ = [
    "BenchmarkProtocol",
    "register_external_benchmark",
    "list_external_benchmarks",
    "external_benchmark_registry_for_test",
]


@runtime_checkable
class BenchmarkProtocol(Protocol):
    """Minimum interface a benchmark dataset must satisfy.

    Anything that exposes ``name`` (str), ``version`` (str) and a
    ``load()`` method returning an iterator of
    :class:`~lub.benchmarks.base.Example` records satisfies this Protocol
    and can be passed to the benchmark runner.

    The :class:`~lub.benchmarks.base.Dataset` ABC already satisfies this
    Protocol structurally, so existing concrete datasets (FinQA, ConvFinQA,
    etc.) are valid ``BenchmarkProtocol`` implementations without any
    code change.
    """

    @property
    def name(self) -> str:
        """Return the stable short identifier of the benchmark."""
        ...

    @property
    def version(self) -> str:
        """Return the version string of the benchmark dataset."""
        ...

    def load(self) -> Iterator[Example]:
        """Yield :class:`Example` records for this benchmark."""
        ...


# ---------------------------------------------------------------------------
# External-plugin registry (additive; does not touch base._LAZY_REGISTRY)
# ---------------------------------------------------------------------------

_EXTERNAL_BENCHMARK_REGISTRY: dict[str, BenchmarkProtocol] = {}


def register_external_benchmark(key: str, dataset: BenchmarkProtocol) -> None:
    """Register an external benchmark dataset by stable key.

    Intended for domain plug-ins (e.g. ``lub.domains.banking.benchmarks``,
    third-party packages) to expose datasets via the public surface
    without modifying the hardcoded ``_LAZY_REGISTRY`` dict in
    :mod:`lub.benchmarks.base`.

    Args:
        key: Stable short identifier (e.g. ``"medqa"``, ``"loan_default"``).
            Must be non-empty and unique across all registrations.
        dataset: Any object satisfying :class:`BenchmarkProtocol`.

    Raises:
        ValueError: If ``key`` is empty.
        TypeError: If ``dataset`` does not satisfy :class:`BenchmarkProtocol`.
        KeyError: If ``key`` is already registered.
    """
    if not key:
        raise ValueError("key must be a non-empty string")
    if not isinstance(dataset, BenchmarkProtocol):
        raise TypeError(
            f"dataset {type(dataset).__name__!r} does not satisfy "
            f"BenchmarkProtocol (needs name, version, load())"
        )
    if key in _EXTERNAL_BENCHMARK_REGISTRY:
        raise KeyError(f"benchmark key {key!r} already registered externally")
    _EXTERNAL_BENCHMARK_REGISTRY[key] = dataset


def list_external_benchmarks() -> list[str]:
    """Return all externally-registered benchmark keys, sorted.

    Distinct from :meth:`Dataset.list_datasets` which only sees datasets
    registered through the inheritance / lazy-import path. Domain
    plug-ins that register via :func:`register_external_benchmark` show
    up here.
    """
    return sorted(_EXTERNAL_BENCHMARK_REGISTRY)


# Sanity: check at import time that the existing Dataset ABC satisfies
# the new Protocol -- if a future refactor breaks the structural match,
# we want to know immediately rather than discover it via a v0.3+ plug-in.
# This is a class-level structural check, not a runtime instance check.
# Using explicit raise (not assert) so the check survives `python -O`.
for _attr in ("name", "version", "load"):
    if not hasattr(Dataset, _attr):
        raise TypeError(
            f"Dataset must expose .{_attr} to satisfy BenchmarkProtocol (missing on {Dataset!r})"
        )
del _attr


def external_benchmark_registry_for_test() -> dict[str, BenchmarkProtocol]:
    """Return a mutable view of the external-benchmark registry for test save/restore.

    Tests should use this instead of touching the private
    ``_EXTERNAL_BENCHMARK_REGISTRY`` directly.
    """
    return _EXTERNAL_BENCHMARK_REGISTRY
