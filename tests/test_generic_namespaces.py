# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Sanity tests for the generic-first namespaces shipped in pass 30.

These tests pin the empty-namespace shape so the placeholders cannot be
silently removed before the v0.3+ migration moves real content into them.

Spec: planning/30_Generic_Architecture_Spec_2026-04-25.md.
"""

from __future__ import annotations

import importlib

import pytest

# ---------------------------------------------------------------------------
# lub.domains -- empty namespace for domain extensions
# ---------------------------------------------------------------------------


def test_lub_domains_imports_cleanly() -> None:
    """The domains namespace must import without side effects."""
    mod = importlib.import_module("lub.domains")
    assert mod is not None


def test_lub_domains_exports_empty_all() -> None:
    """v0.1 ships ``__all__ = ["banking"]`` (skeleton re-export only).

    Originally pass 30 shipped this namespace empty (see commented-out
    history below); pass 33 (CHANGES_2026-04-26 §1.11) shipped the
    ``banking`` skeleton sub-namespace so v0.3-targeted code can already
    import from ``lub.domains.banking``. Test name is preserved for
    blame stability; the assertion now pins the post-pass-33 surface.
    """
    import lub.domains

    assert lub.domains.__all__ == ["banking"]


def test_lub_domains_has_docstring() -> None:
    """The docstring documents the v0.3+ migration intent."""
    import lub.domains

    assert lub.domains.__doc__ is not None
    assert "domain" in lub.domains.__doc__.lower()
    assert "v0.3" in lub.domains.__doc__


# ---------------------------------------------------------------------------
# lub.compliance -- empty namespace for pluggable compliance frameworks
# ---------------------------------------------------------------------------


def test_lub_compliance_imports_cleanly() -> None:
    """The compliance namespace must import without side effects."""
    mod = importlib.import_module("lub.compliance")
    assert mod is not None


def test_lub_compliance_exports_empty_all() -> None:
    """v0.1 ships ``__all__ = ["frameworks"]`` (skeleton re-export only).

    Originally pass 30 shipped this namespace empty; pass 33
    (CHANGES_2026-04-26 §1.11) shipped the ``frameworks`` skeleton
    sub-namespace with seven framework modules so v0.3-targeted code
    can already import from ``lub.compliance.frameworks.<name>``. Test
    name preserved for blame stability; the assertion now pins the
    post-pass-33 surface.
    """
    import lub.compliance

    assert lub.compliance.__all__ == ["frameworks"]


def test_lub_compliance_has_docstring() -> None:
    """The docstring documents the v0.3+ migration intent."""
    import lub.compliance

    assert lub.compliance.__doc__ is not None
    assert "compliance" in lub.compliance.__doc__.lower()
    assert "v0.3" in lub.compliance.__doc__


# ---------------------------------------------------------------------------
# lub.benchmarks.protocol -- explicit Protocol surface for benchmark plug-ins
# ---------------------------------------------------------------------------


def test_benchmark_protocol_importable() -> None:
    """The Protocol surface must be importable from lub.benchmarks.protocol."""
    from lub.benchmarks.protocol import BenchmarkProtocol

    assert BenchmarkProtocol is not None


def test_benchmark_protocol_is_runtime_checkable() -> None:
    """isinstance(...) checks against BenchmarkProtocol must work."""
    from lub.benchmarks.protocol import BenchmarkProtocol

    # @runtime_checkable means isinstance() is supported.
    class _StubBenchmark:
        @property
        def name(self) -> str:
            return "stub"

        @property
        def version(self) -> str:
            return "0.0.0"

        def load(self):  # noqa: ANN201
            return iter([])

    assert isinstance(_StubBenchmark(), BenchmarkProtocol)


def test_existing_dataset_satisfies_benchmark_protocol() -> None:
    """The current Dataset ABC must structurally satisfy the new Protocol.

    This guards against future refactors of Dataset accidentally breaking
    the duck-type contract that v0.3+ domain plug-ins will rely on.
    """
    from lub.benchmarks.base import Dataset
    from lub.benchmarks.protocol import BenchmarkProtocol

    # Class-level structural check (Protocol attributes present on the ABC).
    for attr in ("name", "version", "load"):
        assert hasattr(Dataset, attr), (
            f"Dataset must expose .{attr} to satisfy BenchmarkProtocol"
        )
    # The Protocol class itself must be defined.
    assert BenchmarkProtocol is not None


def test_register_external_benchmark_validates_protocol() -> None:
    """register_external_benchmark must reject objects missing the Protocol."""
    from lub.benchmarks.protocol import register_external_benchmark

    class _Broken:
        # missing .name, .version, .load
        pass

    with pytest.raises(TypeError, match="BenchmarkProtocol"):
        register_external_benchmark("broken", _Broken())  # type: ignore[arg-type]


def test_register_external_benchmark_rejects_empty_key() -> None:
    """Empty key must fail fast."""
    from lub.benchmarks.protocol import register_external_benchmark

    class _Stub:
        @property
        def name(self) -> str:
            return "stub"

        @property
        def version(self) -> str:
            return "0.0.0"

        def load(self):  # noqa: ANN201
            return iter([])

    with pytest.raises(ValueError, match="non-empty"):
        register_external_benchmark("", _Stub())


def test_register_external_benchmark_rejects_duplicate_key() -> None:
    """Re-registering the same key must raise ``KeyError``.

    Pins the contract documented in ``register_external_benchmark``:
    ``raise KeyError(f"benchmark key {key!r} already registered externally")``.
    A v0.3+ plug-in that double-registers is a configuration bug, not a
    silent overwrite -- catching it surfaces the conflict at the
    registration site rather than at first use.
    """
    from lub.benchmarks.protocol import (
        external_benchmark_registry_for_test,
        register_external_benchmark,
    )

    _EXTERNAL_BENCHMARK_REGISTRY = external_benchmark_registry_for_test()

    # Snapshot + restore so this test does not pollute global state for
    # other tests that may also exercise the external registry.
    saved = dict(_EXTERNAL_BENCHMARK_REGISTRY)
    _EXTERNAL_BENCHMARK_REGISTRY.clear()
    try:

        class _Stub:
            @property
            def name(self) -> str:
                return "dup"

            @property
            def version(self) -> str:
                return "0.0.0"

            def load(self):  # noqa: ANN201
                return iter([])

        register_external_benchmark("dup_key", _Stub())
        with pytest.raises(KeyError, match="already registered"):
            register_external_benchmark("dup_key", _Stub())
    finally:
        _EXTERNAL_BENCHMARK_REGISTRY.clear()
        _EXTERNAL_BENCHMARK_REGISTRY.update(saved)


def test_list_external_benchmarks_returns_sorted_list() -> None:
    """list_external_benchmarks must return a sorted list of registered keys."""
    from lub.benchmarks.protocol import (
        external_benchmark_registry_for_test,
        list_external_benchmarks,
        register_external_benchmark,
    )

    _EXTERNAL_BENCHMARK_REGISTRY = external_benchmark_registry_for_test()

    # Snapshot + restore so this test does not pollute global state for
    # other tests that may also exercise the external registry.
    saved = dict(_EXTERNAL_BENCHMARK_REGISTRY)
    _EXTERNAL_BENCHMARK_REGISTRY.clear()
    try:

        class _Stub:
            def __init__(self, name: str) -> None:
                self._name = name

            @property
            def name(self) -> str:
                return self._name

            @property
            def version(self) -> str:
                return "0.0.0"

            def load(self):  # noqa: ANN201
                return iter([])

        register_external_benchmark("zebra", _Stub("zebra"))
        register_external_benchmark("alpha", _Stub("alpha"))
        register_external_benchmark("middle", _Stub("middle"))

        assert list_external_benchmarks() == ["alpha", "middle", "zebra"]
    finally:
        _EXTERNAL_BENCHMARK_REGISTRY.clear()
        _EXTERNAL_BENCHMARK_REGISTRY.update(saved)
