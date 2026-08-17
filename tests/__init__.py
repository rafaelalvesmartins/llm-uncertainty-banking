# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Test helpers and fixtures."""

from __future__ import annotations

from lub.types import BenchmarkResult


def make_benchmark_result(**overrides: object) -> BenchmarkResult:
    """Shared factory for a representative :class:`BenchmarkResult`.

    Tests that need a ``BenchmarkResult`` should call this instead of
    duplicating the base-dict boilerplate. Pass keyword overrides to
    change individual fields.
    """
    base: dict = {
        "repo_version": "0.0.1",
        "backend": "DummyBackend:dummy-0",
        "estimator": "token_logprob",
        "dataset": "br_regulatory",
        "dataset_version": "0.1.0",
        "n": 20,
        "accuracy": 0.75,
        "ece": 0.08,
        "refusal_auroc": 0.82,
        "miscalibration_area": 0.06,
        "sharpness": 0.12,
        "missing_ratio": 0.10,
        "prr": 0.55,
        "metrics": {
            "accuracy": 0.75,
            "ece": 0.08,
            "rmsce": 0.05,
            "refusal_auroc": 0.82,
            "reversed_pairs_proportion": 0.18,
            "brier": 0.18,
            "sharpness": 0.12,
            "miscalibration_area": 0.06,
            "missing_ratio": 0.10,
            "prr": 0.55,
            "spearman": 0.42,
            "kendall_tau": 0.35,
            "aurc": 0.12,
            "auucc": 0.68,
            "crps_from_confidence": 0.10,
            "negative_log_likelihood": 0.35,
        },
        "python_version": "3.12",
        "package_versions": {"lub": "0.0.1"},
        "dataset_hash": "a" * 64,
        "seed": 0,
    }
    base.update(overrides)
    return BenchmarkResult(**base)


__all__ = ["make_benchmark_result"]
