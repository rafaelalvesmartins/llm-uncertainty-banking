# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from lub.benchmarks.base import Dataset, Example
from lub.benchmarks.runner import BenchmarkRunner, content_hash, exact_match
from lub.types import BenchmarkResult, UncertaintyResult


class _StaticDataset(Dataset):
    def __init__(self, examples: list[Example], name: str = "static") -> None:
        self._examples = examples
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return "1.0"

    def load(self) -> Iterator[Example]:
        yield from self._examples


class _ScriptedPipeline:
    """Return a deterministic UncertaintyResult per prompt."""

    def __init__(self, answers: dict[str, tuple[str, float]]) -> None:
        self._answers = answers
        self.backend = type("B", (), {"name": "scripted-backend"})()
        self.estimator = type("E", (), {"name": "scripted-estimator"})()

    def answer(self, prompt: str) -> UncertaintyResult:
        entry = self._answers[prompt]
        if len(entry) == 3:
            text, conf, refuse = entry
        else:
            text, conf = entry
            refuse = False
        return UncertaintyResult(
            answer=text,
            confidence=conf,
            should_refuse=bool(refuse),
        )


def _example(i: int, q: str, a: str) -> Example:
    return Example(id=f"ex-{i}", question=q, gold_answer=a, metadata={})


def test_exact_match_normalizes_punct_and_case() -> None:
    # `.` and `,` are preserved so numeric answers like "4.5" and "1,234"
    # survive — see _normalize() in runner.py. Exclamation marks, question
    # marks, etc. are still stripped.
    assert exact_match("Hello World!", "hello world")
    assert exact_match("YES.", "yes.")
    assert not exact_match("yes", "no")


def test_exact_match_numeric_survives_decimal_and_thousands() -> None:
    assert exact_match("4.5", "4.5%")
    assert exact_match("1,234", "1234")
    assert exact_match("1,234.50", "1234.5")


def test_runner_scores_perfect_pipeline(tmp_path: Path) -> None:
    examples = [
        _example(1, "q1", "a1"),
        _example(2, "q2", "a2"),
    ]
    pipe = _ScriptedPipeline({"q1": ("a1", 0.95), "q2": ("a2", 0.9)})
    runner = BenchmarkRunner(pipe, _StaticDataset(examples), results_dir=tmp_path)
    record = runner.run(seed=0)
    assert isinstance(record, BenchmarkResult)
    assert record.n == 2
    assert record.accuracy == pytest.approx(1.0)
    assert 0.0 <= record.ece <= 1.0


def test_runner_partial_accuracy(tmp_path: Path) -> None:
    examples = [
        _example(1, "q1", "a1"),
        _example(2, "q2", "a2"),
        _example(3, "q3", "a3"),
        _example(4, "q4", "a4"),
    ]
    pipe = _ScriptedPipeline(
        {
            "q1": ("a1", 0.9),
            "q2": ("wrong", 0.1),
            "q3": ("a3", 0.9),
            "q4": ("wrong", 0.1),
        }
    )
    runner = BenchmarkRunner(pipe, _StaticDataset(examples), results_dir=tmp_path)
    record = runner.run(write=False)
    assert record.accuracy == pytest.approx(0.5)


def test_runner_writes_json(tmp_path: Path) -> None:
    pipe = _ScriptedPipeline({"q": ("a", 0.8)})
    runner = BenchmarkRunner(
        pipe, _StaticDataset([_example(1, "q", "a")]), results_dir=tmp_path
    )
    runner.run(seed=42)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["dataset"] == "static"
    assert payload["n"] == 1
    assert payload["seed"] == 42


def test_runner_empty_dataset_raises(tmp_path: Path) -> None:
    pipe = _ScriptedPipeline({})
    runner = BenchmarkRunner(pipe, _StaticDataset([]), results_dir=tmp_path)
    with pytest.raises(ValueError):
        runner.run(write=False)


def test_runner_tracks_missing_ratio(tmp_path: Path) -> None:
    examples = [
        _example(1, "q1", "a1"),
        _example(2, "q2", "a2"),
        _example(3, "q3", "a3"),
        _example(4, "q4", "a4"),
    ]
    pipe = _ScriptedPipeline(
        {
            "q1": ("a1", 0.9, False),
            "q2": ("a2", 0.1, True),
            "q3": ("a3", 0.9, False),
            "q4": ("a4", 0.05, True),
        }
    )
    runner = BenchmarkRunner(pipe, _StaticDataset(examples), results_dir=tmp_path)
    record = runner.run(write=False)
    assert record.missing_ratio == pytest.approx(0.5)


def test_runner_respects_limit(tmp_path: Path) -> None:
    examples = [_example(i, f"q{i}", "a") for i in range(10)]
    answers = {f"q{i}": ("a", 0.9) for i in range(10)}
    pipe = _ScriptedPipeline(answers)
    runner = BenchmarkRunner(pipe, _StaticDataset(examples), results_dir=tmp_path)
    record = runner.run(limit=3, write=False)
    assert record.n == 3


def test_content_hash_stable_across_volatile_fields() -> None:
    base = BenchmarkResult(
        repo_version="0.0.1",
        backend="b",
        estimator="e",
        dataset="d",
        n=1,
        accuracy=1.0,
        ece=0.0,
        refusal_auroc=1.0,
        python_version="3.12",
        package_versions={"numpy": "1.26.0"},
        dataset_hash="deadbeef",
        seed=0,
    )
    other = base.model_copy(
        update={
            "timestamp": "different",
            "package_versions": {"numpy": "2.0.0"},
            "git_sha": "abc123",
        }
    )
    assert content_hash(base) == content_hash(other)


def test_result_records_which_correctness_scorer_produced_the_accuracy(tmp_path: Path) -> None:
    """Provenance: ``accuracy`` now DEPENDS on a user-selectable scorer (``lub benchmark
    --correctness``), so the persisted record must say which one produced it.

    Without this, two runs with the same model/estimator/dataset but different scorers are
    indistinguishable in the evidence file — they report different accuracies with no way to
    tell why, and ``lub repro`` cannot faithfully rebuild the run. Making the scorer
    selectable without recording it would have made the evidence LESS reproducible.
    """
    from lub.benchmarks.correctness import fuzzy_match

    examples = [_example(1, "q1", "a1"), _example(2, "q2", "a2")]
    pipe = _ScriptedPipeline({"q1": ("a1", 0.9), "q2": ("a2", 0.9)})

    rec = BenchmarkRunner(
        pipe, _StaticDataset(examples), results_dir=tmp_path, correctness_fn=fuzzy_match
    ).run(write=False)
    assert rec.correctness == "fuzzy_match"

    default = BenchmarkRunner(pipe, _StaticDataset(examples), results_dir=tmp_path).run(write=False)
    assert default.correctness == "exact_match"


def test_old_result_files_without_a_correctness_field_still_load() -> None:
    """Backward compatibility: records persisted before the field existed must still validate
    (the model is ``extra='forbid'``/frozen, so a DEFAULTED field is the only safe way to add
    one — an unqualified required field would reject every historical evidence file)."""
    from lub.types import BenchmarkResult

    old = {
        "repo_version": "0.1.0",
        "backend": "dummy",
        "estimator": "token_logprob",
        "dataset": "br_regulatory",
        "n": 5,
        "accuracy": 0.5,
        "ece": 0.1,
        "refusal_auroc": 0.6,
        "python_version": "3.12.0",
        "package_versions": {"numpy": "1.26.0"},
        "dataset_hash": "deadbeef",
    }
    rec = BenchmarkResult.model_validate(old)
    assert rec.correctness == "exact_match"  # the historical default
