# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Benchmark runner.

Iterates a :class:`~lub.benchmarks.base.Dataset` through an uncertainty
pipeline, computes calibration metrics, and persists a signed-off
:class:`~lub.types.BenchmarkResult` as JSON under
``benchmarks/results/<run_id>.json``.

The runner is intentionally deterministic given the same ``seed``: dataset
order comes from ``Dataset.load()``, predictions come from ``pipeline.answer``,
and the only randomness we seed here is Python/NumPy for any downstream
sampling the estimator may drive.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import random
import uuid
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import structlog

from lub.benchmarks.base import Dataset, Example
from lub.benchmarks.correctness import (
    CorrectnessFn,
    choice_match,
    exact_match,
    fuzzy_match,
)
from lub.benchmarks.provenance import Provenance
from lub.calibration.metrics import compute_all
from lub.protocols import PipelineProto
from lub.types import BenchmarkResult

_LOG = structlog.get_logger(__name__)


def _pipeline_label(
    pipeline: PipelineProto,
    attr: str,
    default: str,
) -> str:
    component = getattr(pipeline, attr, None)
    if component is None:
        return default
    for key in ("REGISTRY_KEY", "NAME"):
        classvar = getattr(type(component), key, None)
        if isinstance(classvar, str) and classvar:
            return classvar
    name = getattr(component, "name", None)
    if isinstance(name, str) and name:
        return name
    return type(component).__name__


class BenchmarkRunner:
    """Runs a pipeline over a dataset and emits a :class:`BenchmarkResult`.

    Parameters
    ----------
    pipeline:
        Any object implementing ``answer(prompt) -> UncertaintyResult``. In
        practice this is :class:`lub.pipeline.UncertaintyPipeline`, but a
        structural type is accepted so tests can pass in a mock.
    dataset:
        A concrete :class:`Dataset`.
    correctness_fn:
        Optional callable ``(pred, gold) -> bool``. Defaults to
        :func:`exact_match` after string normalization.
    results_dir:
        Where to write result JSON. Defaults to ``benchmarks/results``
        under the current working directory.
    """

    def __init__(
        self,
        pipeline: PipelineProto,
        dataset: Dataset,
        *,
        correctness_fn: CorrectnessFn | None = None,
        results_dir: Path | str = Path("benchmarks/results"),
    ) -> None:
        self.pipeline = pipeline
        self.dataset = dataset
        self.correctness_fn: CorrectnessFn = correctness_fn or exact_match
        self.results_dir = Path(results_dir)

        warnings = dataset.validate(limit=5)
        for w in warnings:
            _LOG.warning("benchmark.dataset_validation", warning=w)

    def _iter_examples(self, limit: int | None) -> Iterable[Example]:
        if limit is None:
            return self.dataset.load()
        return itertools.islice(self.dataset.load(), limit)

    @staticmethod
    def _make_run_id(dataset_name: str, seed: int) -> str:
        token = uuid.uuid4().hex[:8]
        return f"{dataset_name}-seed{seed}-{token}"

    def run(
        self,
        limit: int | None = None,
        seed: int = 0,
        *,
        write: bool = True,
    ) -> BenchmarkResult:
        """Execute the benchmark and return the persisted record.

        Parameters
        ----------
        limit:
            If given, stop after this many examples (useful for smoke tests).
        seed:
            Seeds ``random`` and ``numpy.random`` before the first call.
        write:
            If ``True`` (default), persist the JSON to ``results_dir``.
        """
        if limit is not None and limit < 1:
            raise ValueError(f"limit must be >= 1, got {limit}")
        random.seed(seed)
        np.random.seed(seed)

        dataset_name = self.dataset.name
        backend_label = _pipeline_label(self.pipeline, "backend", default="unknown-backend")
        estimator_label = _pipeline_label(self.pipeline, "estimator", default="unknown-estimator")

        _LOG.info(
            "benchmark.start",
            dataset=dataset_name,
            dataset_version=self.dataset.version,
            backend=backend_label,
            estimator=estimator_label,
            limit=limit,
            seed=seed,
        )

        confs: list[float] = []
        correct: list[bool] = []
        missing: list[bool] = []
        n_errors = 0
        id_hasher = hashlib.sha256()
        for example in self._iter_examples(limit):
            try:
                result = self.pipeline.answer(example.question)
            except (RuntimeError, ValueError, OSError) as exc:
                _LOG.warning(
                    "benchmark.pipeline_error",
                    error=str(exc),
                    example_id=example.id,
                    n=len(confs),
                )
                from lub.types import UncertaintyResult

                result = UncertaintyResult(
                    answer="",
                    confidence=0.0,
                    raw_scores={},
                    samples=[],
                    should_refuse=True,
                )
                n_errors += 1
            confs.append(float(result.confidence))
            correct.append(bool(self.correctness_fn(result.answer, example.gold_answer)))
            missing.append(bool(result.should_refuse))
            id_hasher.update(example.id.encode("utf-8"))
            id_hasher.update(b"\n")
            if len(confs) % 25 == 0:
                _LOG.info("benchmark.progress", n=len(confs), dataset=dataset_name)

        n = len(confs)
        if n == 0:
            raise ValueError(f"Dataset {dataset_name!r} produced zero examples; nothing to score.")

        metrics = compute_all(
            np.asarray(confs, dtype=np.float64),
            np.asarray(correct, dtype=bool),
            missing=np.asarray(missing, dtype=bool),
        )

        prov = Provenance.capture()
        # Persist every metric compute_all returns -- drops the silent
        # drop of rmsce / brier / reversed_pairs_proportion / spearman /
        # kendall_tau that used to happen when the runner hard-coded
        # which keys to carry into BenchmarkResult.
        metrics_dict = {k: float(v) for k, v in metrics.items() if k != "n"}
        record = BenchmarkResult(
            repo_version=prov.repo_version,
            backend=backend_label,
            estimator=estimator_label,
            dataset=dataset_name,
            dataset_version=self.dataset.version,
            # The scorer is selectable and changes `accuracy`, so the evidence file must name
            # it (see BenchmarkResult.correctness). Closures built by factories like
            # `choice_match` have no useful __name__ — record them honestly as "custom".
            correctness=getattr(self.correctness_fn, "__name__", "custom") or "custom",
            n=n,
            accuracy=float(metrics["accuracy"]),
            ece=float(metrics["ece"]),
            refusal_auroc=float(metrics["refusal_auroc"]),
            miscalibration_area=float(metrics["miscalibration_area"]),
            sharpness=float(metrics["sharpness"]),
            missing_ratio=float(metrics["missing_ratio"]),
            prr=float(metrics["prr"]),
            metrics=metrics_dict,
            python_version=prov.python_version,
            package_versions=prov.package_versions,
            dataset_hash=id_hasher.hexdigest(),
            git_sha=prov.git_sha,
            seed=seed,
        )

        _LOG.info(
            "benchmark.done",
            dataset=dataset_name,
            n=n,
            n_errors=n_errors,
            accuracy=record.accuracy,
            ece=record.ece,
            refusal_auroc=record.refusal_auroc,
        )

        if write:
            run_id = self._make_run_id(dataset_name, seed)
            self._write(record, run_id)

        return record

    def _write(self, record: BenchmarkResult, run_id: str) -> Path:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        out = self.results_dir / f"{run_id}.json"
        payload = record.model_dump()
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _LOG.info("benchmark.written", path=str(out))
        return out


def content_hash(record: BenchmarkResult) -> str:
    """Stable hash of a result record, excluding volatile fields.

    Used by ``lub repro`` to verify that two runs produced identical scores
    without being fooled by timestamps or package-version drift.
    """
    volatile = {"timestamp", "package_versions", "git_sha"}
    payload = {k: v for k, v in record.model_dump().items() if k not in volatile}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


__all__ = [
    "BenchmarkRunner",
    "CorrectnessFn",
    "choice_match",
    "content_hash",
    "exact_match",
    "fuzzy_match",
]
