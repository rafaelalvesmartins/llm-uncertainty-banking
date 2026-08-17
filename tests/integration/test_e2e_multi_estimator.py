# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Extra end-to-end integration tests.

``test_end_to_end.py`` covers the single happy path from the README.
These three tests cover cross-layer flows that a single happy-path test
can miss: (1) guard with each policy decision exercised, (2) a
multi-estimator benchmark aggregated into one report, (3) round-tripping
a signed BenchmarkResult through JSON persistence with every new field
(`prr`, `dataset_version`, `missing_ratio`) preserved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lub.benchmarks import BenchmarkRunner, BrazilianRegulatoryDataset
from lub.guard import UncertaintyGuard
from lub.pipeline import UncertaintyPipeline
from lub.policies import PolicyDecision
from lub.reports import AIRMFReporter
from lub.types import BenchmarkResult

# --- E2E #1: Guard with every PolicyDecision ------------------------


def test_guard_round_trip_covers_all_policy_decisions() -> None:
    """One pipeline, three guards with different on_fail policies, all
    applied to the same prompt. Verifies the cross-layer path from
    estimator → pipeline → guard → GuardResult works under every
    governance action."""
    pipe = UncertaintyPipeline.from_pretrained(
        model="dummy-model",
        backend="dummy",
        estimator="token_logprob",
        refusal_threshold=0.0,
    )

    abstain_guard = UncertaintyGuard(
        pipe, threshold=0.99, on_fail=PolicyDecision.ABSTAIN,
    )
    flag_guard = UncertaintyGuard(
        pipe, threshold=0.99, on_fail=PolicyDecision.FLAG,
    )
    passthrough_guard = UncertaintyGuard(
        pipe, threshold=0.0, on_fail=PolicyDecision.PASSTHROUGH,
    )

    prompt = "What is the Basel III minimum CET1 ratio?"

    abstain = abstain_guard(prompt)
    flag = flag_guard(prompt)
    passthrough = passthrough_guard(prompt)

    # Same underlying answer, different post-policy output.
    assert abstain.raw.answer == flag.raw.answer == passthrough.raw.answer
    assert "[ABSTAIN" in abstain.output
    assert flag.output == flag.raw.answer
    assert passthrough.output == passthrough.raw.answer

    # Each policy maps to the expected AI RMF sub-category.
    assert abstain.rmf_subcategory == "MANAGE 2.3"
    assert flag.rmf_subcategory == "MANAGE 2.4"
    assert passthrough.rmf_subcategory == "GOVERN 3.2"

    # RAISE policy should raise, not return.
    raise_guard = UncertaintyGuard(
        pipe, threshold=0.99, on_fail=PolicyDecision.RAISE,
    )
    with pytest.raises(RuntimeError):
        raise_guard(prompt)


# --- E2E #2: Multi-estimator benchmark → single AI RMF report -------


def test_multiple_estimators_aggregate_into_single_report(tmp_path: Path) -> None:
    """Three estimators run against the same 5-example dataset slice,
    then all three BenchmarkResults are passed to one AIRMFReporter to
    verify the report renders a 'Run 1/2/3' section per estimator."""
    estimators = ["token_logprob", "self_consistency", "p_true"]
    results: list[BenchmarkResult] = []
    for est in estimators:
        pipe = UncertaintyPipeline.from_pretrained(
            model="dummy-model",
            backend="dummy",
            estimator=est,
            refusal_threshold=0.0,
        )
        runner = BenchmarkRunner(
            pipeline=pipe,
            dataset=BrazilianRegulatoryDataset(),
            results_dir=tmp_path / est,
        )
        results.append(runner.run(limit=5, seed=0))

    assert len(results) == 3
    assert {r.estimator for r in results} == {
        "token_logprob", "self_consistency", "p_true",
    }

    reporter = AIRMFReporter(results=results)
    md = reporter.render(format="md")

    # The template renders one section per run.
    assert "Run 1" in md
    assert "Run 2" in md
    assert "Run 3" in md
    for est in estimators:
        assert est in md


# --- E2E #3: BenchmarkResult JSON round-trip preserves new fields ---


def test_benchmark_result_json_round_trip_preserves_new_fields(tmp_path: Path) -> None:
    """The signed BenchmarkResult record added `prr`, `dataset_version`,
    and `missing_ratio` after v0.0.1. Verify that writing one record to
    disk and loading it back through ``model_validate_json`` preserves
    every field, including the post-v0.0.1 additions."""
    pipe = UncertaintyPipeline.from_pretrained(
        model="dummy-model",
        backend="dummy",
        estimator="token_logprob",
        refusal_threshold=0.0,
    )
    dataset = BrazilianRegulatoryDataset()
    runner = BenchmarkRunner(
        pipeline=pipe, dataset=dataset, results_dir=tmp_path,
    )
    original = runner.run(limit=3, seed=42)

    written = list(tmp_path.glob("*.json"))
    assert len(written) == 1

    payload = json.loads(written[0].read_text(encoding="utf-8"))
    # Every field that was added after v0.0.1 must be present in the JSON.
    assert "prr" in payload
    assert "dataset_version" in payload
    assert "missing_ratio" in payload
    assert payload["seed"] == 42
    assert payload["dataset"] == "br_regulatory"

    reloaded = BenchmarkResult.model_validate_json(written[0].read_text(encoding="utf-8"))
    assert reloaded.n == original.n
    assert reloaded.accuracy == pytest.approx(original.accuracy)
    assert reloaded.ece == pytest.approx(original.ece)
    assert reloaded.prr == pytest.approx(original.prr)
    assert reloaded.dataset_version == original.dataset_version
    assert reloaded.missing_ratio == pytest.approx(original.missing_ratio)
    assert reloaded.seed == original.seed
    assert reloaded.dataset_hash == original.dataset_hash
