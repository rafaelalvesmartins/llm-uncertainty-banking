# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""End-to-end example: registering an external benchmark via the Protocol.

This is the v0.3+ plug-in pattern from spec 30 §4 demonstrated as a runnable
test. A hypothetical third-party package (e.g. `acme-healthcare-bench`)
would expose a benchmark like this and register it -- the runner then
sees it via `list_external_benchmarks()`.

The example is intentionally tiny (5-example synthetic dataset) so it
serves as the canonical "how to write a benchmark plugin" reference for
external contributors.

Spec: planning/30_Generic_Architecture_Spec_2026-04-25.md §4.
"""

from __future__ import annotations

from collections.abc import Iterator

from lub.benchmarks.base import Example
from lub.benchmarks.protocol import (
    BenchmarkProtocol,
    external_benchmark_registry_for_test,
    list_external_benchmarks,
    register_external_benchmark,
)

_EXTERNAL_BENCHMARK_REGISTRY = external_benchmark_registry_for_test()


# This is what an external plug-in author writes:
class TinyMedQABenchmark:
    """Hypothetical 'medqa' benchmark from a third-party plug-in package.

    Notice it does NOT inherit from lub.benchmarks.base.Dataset; the
    Protocol surface is enough. This is exactly the duck-typed escape
    hatch spec 30 §4 calls out.
    """

    @property
    def name(self) -> str:
        return "medqa"

    @property
    def version(self) -> str:
        return "v1.0"

    def load(self) -> Iterator[Example]:
        yield Example(
            id="med-001",
            question="What is the first-line treatment for community-acquired pneumonia?",
            gold_answer="amoxicillin",
            metadata={"specialty": "pulmonology"},
        )
        yield Example(
            id="med-002",
            question="Hba1c >= 6.5 is diagnostic of which condition?",
            gold_answer="diabetes",
            metadata={"specialty": "endocrinology"},
        )


def test_plugin_satisfies_protocol():
    """The plug-in must satisfy BenchmarkProtocol structurally."""
    assert isinstance(TinyMedQABenchmark(), BenchmarkProtocol)


def test_plugin_can_register_and_list():
    """register_external_benchmark + list_external_benchmarks round-trip."""
    saved = dict(_EXTERNAL_BENCHMARK_REGISTRY)
    _EXTERNAL_BENCHMARK_REGISTRY.clear()
    try:
        register_external_benchmark("medqa", TinyMedQABenchmark())
        assert "medqa" in list_external_benchmarks()
        assert _EXTERNAL_BENCHMARK_REGISTRY["medqa"].name == "medqa"
    finally:
        _EXTERNAL_BENCHMARK_REGISTRY.clear()
        _EXTERNAL_BENCHMARK_REGISTRY.update(saved)


def test_plugin_load_yields_examples():
    """The plug-in's .load() must yield Example records."""
    examples = list(TinyMedQABenchmark().load())
    assert len(examples) == 2
    assert examples[0].id == "med-001"
    assert examples[0].metadata["specialty"] == "pulmonology"
    assert all(isinstance(e, Example) for e in examples)
