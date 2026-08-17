# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Shared dataclasses and pydantic models used across the library."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class Generation:
    """A single model completion.

    ``logprobs`` follows a strict convention: ``None`` means the backend
    did not provide per-token log-probabilities at all (e.g. a blackbox
    SDK that doesn't expose them), while an empty list ``[]`` means the
    backend *does* normally provide logprobs but had none for this
    completion (e.g. an early stop, a tokenizer edge case, or a truly
    empty generation). Estimators must distinguish the two: an ``is None``
    check should fall back to a blackbox path, while an empty-list check
    should treat the completion as a zero-confidence answer.
    """

    text: str
    logprobs: list[float] | None = None
    finish_reason: str | None = None


@dataclass(frozen=True)
class TokenLogProbs:
    """Token-level log-probabilities for a (prompt, completion) pair."""

    tokens: list[str]
    logprobs: list[float]

    def __post_init__(self) -> None:
        if len(self.tokens) != len(self.logprobs):
            raise ValueError(
                f"tokens ({len(self.tokens)}) and logprobs ({len(self.logprobs)}) length mismatch"
            )


@dataclass(frozen=True)
class UncertaintyResult:
    """Output of any uncertainty estimator.

    ``confidence`` is a calibrated-ish scalar in ``[0, 1]``. The two
    auxiliary fields have distinct semantics:

    - ``raw_scores`` — **numeric** diagnostics safe to aggregate across
      estimators (entropy, agreement fraction, perplexity, eigen-score).
      Anything that might be averaged, plotted, or logged as a metric.
    - ``diagnostics`` — **free-form** structured data that is not safe
      to aggregate numerically (per-claim breakdowns, raw tokens,
      rail-decision logs). The AI RMF reporter renders these as
      audit-trail attachments, not as metric rows.

    Splitting the two makes ``raw_scores`` type-correct (previously
    ``claim_level`` smuggled ``list[dict]`` through ``# type: ignore``)
    and keeps downstream ``sum(r.raw_scores.values())``-style aggregations
    safe for any estimator.

    The dataclass is **frozen** — attribute bindings cannot be changed
    after construction. Use :func:`dataclasses.replace` to derive a new
    instance with modified fields. Note that the *contents* of mutable
    fields (``raw_scores``, ``diagnostics``) are still mutable; only
    the attribute bindings are immutable.
    """

    answer: str
    confidence: float
    raw_scores: dict[str, float] = field(default_factory=dict)
    samples: list[str] | None = None
    should_refuse: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")

    def with_should_refuse(self, refuse: bool) -> UncertaintyResult:
        """Return a copy with ``should_refuse`` set to ``refuse``."""
        return dataclasses.replace(self, should_refuse=refuse)

    def with_answer(self, answer: str) -> UncertaintyResult:
        """Return a copy with a modified ``answer``."""
        return dataclasses.replace(self, answer=answer)

    def with_raw_scores(self, scores: dict[str, float]) -> UncertaintyResult:
        """Return a copy with ``raw_scores`` replaced by a *new* dict.

        Takes a defensive copy so the caller's dict cannot later mutate
        the stored value - important because ``UncertaintyResult`` is
        frozen but its ``raw_scores`` container is not. Prefer this over
        ``result.raw_scores[key] = value`` in estimators that take a
        base estimator result and want to annotate it.
        """
        return dataclasses.replace(self, raw_scores=dict(scores))


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


class BenchmarkResult(BaseModel):
    """Persisted record of one benchmark run — the unit of evidence.

    The ``metrics`` field carries every key produced by
    :func:`lub.calibration.metrics.compute_all` without schema drift —
    when a new metric is added to ``compute_all``, it appears
    automatically in the persisted record and in the AI RMF report.
    The typed top-level fields (``accuracy``, ``ece``, ...) are
    preserved for backward compatibility with existing result files
    and for pydantic validation of the most-consulted metrics; they
    are also present as keys in ``metrics``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo_version: str
    backend: str
    estimator: str
    dataset: str
    dataset_version: str = ""
    # Which correctness scorer produced ``accuracy``. It is user-selectable
    # (``lub benchmark --correctness``), and the same model/estimator/dataset scores
    # differently under ``exact_match`` vs ``fuzzy_match`` — so without this the evidence
    # file would be ambiguous and ``lub repro`` could not faithfully rebuild the run.
    # Defaulted (not required) so every record persisted before the field existed still
    # validates under ``extra="forbid"``; ``exact_match`` was the historical behaviour.
    correctness: str = "exact_match"
    n: int = Field(ge=0)
    accuracy: float = Field(ge=0.0, le=1.0)
    ece: float = Field(ge=0.0, le=1.0)
    refusal_auroc: float = Field(ge=0.0, le=1.0)
    miscalibration_area: float | None = Field(default=None, ge=0.0, le=1.0)
    sharpness: float | None = Field(default=None, ge=0.0, le=1.0)
    missing_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    prr: float | None = Field(default=None, ge=-1.0, le=1.0)
    metrics: dict[str, float] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=_utc_now_iso)
    python_version: str
    package_versions: dict[str, str]
    dataset_hash: str
    git_sha: str | None = None
    seed: int = 0


__all__ = ["BenchmarkResult", "Generation", "TokenLogProbs", "UncertaintyResult"]
