# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""End-to-end: multi-dataset benchmark → single AI RMF report.

Covers gap #4 from the integration audit: :class:`BenchmarkRunner` is
only exercised against :class:`BrazilianRegulatoryDataset` in e2e
tests, but production usage runs it against multiple dataset classes
(br_regulatory + FinQA-style + credit-scoring) and feeds every
resulting :class:`BenchmarkResult` into one :class:`AIRMFReporter`.

This test defines a hermetic secondary :class:`Dataset` (so we don't
touch FinQA/ConvFinQA/TAT-QA loaders that need HuggingFace), runs both
datasets through the same pipeline, and verifies the aggregated report
contains a run section per dataset.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from lub.benchmarks import BenchmarkRunner, BrazilianRegulatoryDataset
from lub.benchmarks.base import Dataset, Example
from lub.pipeline import UncertaintyPipeline
from lub.reports import AIRMFReporter
from lub.types import BenchmarkResult


class _SyntheticFinQAStyle(Dataset):
    """Small in-memory dataset mimicking a FinQA-style numeric QA set.

    Used by this integration test only — registered under a private
    REGISTRY_KEY so the global registry snapshot in ``tests/conftest.py``
    restores the clean state after the test runs.
    """

    REGISTRY_KEY = "_synthetic_finqa_style"

    @property
    def name(self) -> str:
        return "synthetic_finqa_style"

    @property
    def version(self) -> str:
        return "0.0.1-test"

    def load(self) -> Iterator[Example]:
        rows = [
            ("q1", "What is 2+2?", "4"),
            ("q2", "What is the sum of 10 and 15?", "25"),
            ("q3", "What is 100 minus 37?", "63"),
            ("q4", "What is 12 times 4?", "48"),
            ("q5", "What is 81 divided by 9?", "9"),
        ]
        for id_, question, gold in rows:
            yield Example(
                id=id_,
                question=question,
                gold_answer=gold,
                metadata={"topic": "synthetic_math"},
            )


def _pipeline() -> UncertaintyPipeline:
    return UncertaintyPipeline.from_pretrained(
        model="dummy-multi",
        backend="dummy",
        estimator="token_logprob",
        refusal_threshold=0.0,
    )


def test_two_datasets_aggregate_into_single_airmf_report(tmp_path: Path) -> None:
    """Run the same pipeline against two distinct datasets, feed both
    results into one :class:`AIRMFReporter`, and verify the rendered
    markdown contains a section per run with the correct dataset names.
    """
    pipe = _pipeline()

    regulatory = BrazilianRegulatoryDataset()
    synthetic = _SyntheticFinQAStyle()

    results: list[BenchmarkResult] = []
    for i, ds in enumerate([regulatory, synthetic]):
        runner = BenchmarkRunner(
            pipeline=pipe,
            dataset=ds,
            results_dir=tmp_path / f"run_{i}",
        )
        results.append(runner.run(limit=5, seed=0))

    # Both results carry the expected dataset identity + version.
    assert results[0].dataset == "br_regulatory"
    assert results[1].dataset == "synthetic_finqa_style"
    assert results[0].dataset_version != results[1].dataset_version

    # Every result is a signed BenchmarkResult (dataset_hash covers the slice).
    for r in results:
        assert len(r.dataset_hash) == 64
        assert r.n == 5
        assert 0.0 <= r.accuracy <= 1.0

    reporter = AIRMFReporter(results=results)
    md = reporter.render(format="md")

    # One section per dataset run.
    assert "Run 1" in md
    assert "Run 2" in md
    # Both dataset identities must surface in the report.
    assert "br_regulatory" in md
    assert "synthetic_finqa_style" in md


def test_multi_dataset_json_round_trip_preserves_dataset_identity(
    tmp_path: Path,
) -> None:
    """Every result written by ``BenchmarkRunner`` must round-trip
    through ``BenchmarkResult.model_validate_json`` with its dataset
    identity intact — downstream OSCAL / audit tooling keys off the
    ``dataset`` + ``dataset_version`` pair.
    """
    pipe = _pipeline()
    datasets: list[Dataset] = [BrazilianRegulatoryDataset(), _SyntheticFinQAStyle()]

    for ds in datasets:
        results_dir = tmp_path / ds.name
        BenchmarkRunner(
            pipeline=pipe, dataset=ds, results_dir=results_dir,
        ).run(limit=3, seed=0)

        written = list(results_dir.glob("*.json"))
        assert len(written) == 1
        reloaded = BenchmarkResult.model_validate_json(
            written[0].read_text(encoding="utf-8"),
        )
        assert reloaded.dataset == ds.name
        assert reloaded.dataset_version == ds.version
        assert reloaded.n == 3
