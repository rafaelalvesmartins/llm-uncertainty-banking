# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""End-to-end: answer → benchmark → report → repro against DummyBackend.

This is the flow a model-risk reviewer runs first. It exercises every
layer of the library in a single test without touching the network.
"""

from __future__ import annotations

from pathlib import Path

from lub.benchmarks import BenchmarkRunner, BrazilianRegulatoryDataset, content_hash
from lub.pipeline import UncertaintyPipeline
from lub.reports import AIRMFReporter
from lub.types import BenchmarkResult


def test_full_loop_answer_benchmark_report_repro(tmp_path: Path) -> None:
    # 1. Answer ----------------------------------------------------------
    pipe = UncertaintyPipeline.from_pretrained(
        model="dummy-model",
        backend="dummy",
        estimator="token_logprob",
        refusal_threshold=0.0,
    )
    answer = pipe.answer("What is the Basel III minimum CET1 ratio?")
    assert 0.0 <= answer.confidence <= 1.0
    assert answer.answer

    # 2. Benchmark -------------------------------------------------------
    dataset = BrazilianRegulatoryDataset()
    runner = BenchmarkRunner(
        pipeline=pipe,
        dataset=dataset,
        results_dir=tmp_path / "results",
    )
    result = runner.run(limit=5, seed=0)
    assert isinstance(result, BenchmarkResult)
    assert result.n == 5
    assert result.dataset == "br_regulatory"
    assert result.dataset_version == dataset.version
    # dataset_hash covers the subset actually scored, not the full dataset
    assert len(result.dataset_hash) == 64

    written = list((tmp_path / "results").glob("*.json"))
    assert len(written) == 1

    # 3. Report ----------------------------------------------------------
    reporter = AIRMFReporter(results=[result])
    md_path = reporter.save(tmp_path / "airmf.md", format="md")
    md = md_path.read_text(encoding="utf-8")
    for section in ("## Govern", "## Map", "## Measure", "## Manage"):
        assert section in md
    # The estimator/backend label may appear as either the NAME/REGISTRY_KEY
    # or the class name depending on pipeline internals — accept either.
    assert "token_logprob" in md.lower() or "tokenlogprob" in md.lower()
    assert "dummy" in md.lower()

    # 4. Repro — rerun the pipeline from to_dict() and verify metric parity
    rebuilt = UncertaintyPipeline.from_dict(pipe.to_dict())
    second = BenchmarkRunner(
        pipeline=rebuilt,
        dataset=BrazilianRegulatoryDataset(),
        results_dir=tmp_path / "results2",
    ).run(limit=5, seed=0)

    assert content_hash(second) == content_hash(result)
