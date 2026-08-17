# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Reflexive p(True) uncertainty estimator.

The model is first asked to answer the prompt, then asked a second,
self-referential question: *"Is the proposed answer correct? True/False"*.
Confidence is derived from how strongly the second call favors ``True``
over ``False``, either from its token log-probabilities (white-box path)
or, if logprobs are unavailable, from majority vote over sampled
generations (black-box fallback).

This is a **reflexive** estimator -- it uses the model's own judgment of
its prior answer as the uncertainty signal. Fast, no retrieval, no
calibration set required.

Reference:
    Kadavath, S., Conerly, T., Askell, A., et al. (2022).
    *Language Models (Mostly) Know What They Know.* arXiv:2207.05221.
"""

from __future__ import annotations

from typing import Any

import structlog

from lub._text_utils import normalize_answer
from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty._math_utils import stable_softmax
from lub.uncertainty.base import Estimator

_LOG = structlog.get_logger("lub.uncertainty.p_true")

_PROMPT_TEMPLATE = (
    "Question: {question}\n"
    "Proposed answer: {answer}\n"
    "Is the proposed answer correct? Respond with exactly one word: "
    "True or False.\n"
    "Answer:"
)


def _normalize(text: str) -> str:
    return normalize_answer(text, strip_trailing_punct=True)


class PTrueEstimator(Estimator):
    """Kadavath et al. 2022 reflexive p(True) estimator."""

    REGISTRY_KEY = "p_true"

    def __init__(
        self,
        n_blackbox_samples: int = 5,
        temperature: float = 0.7,
        refusal_threshold: float = 0.5,
    ) -> None:
        # _validate_n_samples uses the generic name "n_samples" in its
        # error message, so we keep an explicit assertion here when the
        # caller passes a clearly invalid value -- callers expect to see
        # "n_blackbox_samples" in the message, not "n_samples".
        if n_blackbox_samples < 1:
            raise ValueError(f"n_blackbox_samples must be >= 1, got {n_blackbox_samples}")
        self.n_blackbox_samples = n_blackbox_samples
        self.temperature = self._validate_temperature(temperature)
        self.refusal_threshold = self._validate_threshold(refusal_threshold)

    def score(
        self,
        backend: BackendProto,
        prompt: str,
        **kwargs: Any,
    ) -> UncertaintyResult:
        """Compute uncertainty score for the given prompt and answer."""
        max_tokens = int(kwargs.get("max_tokens", 256))

        answer_gen = backend.generate(
            prompt,
            n_samples=1,
            temperature=0.0,
            max_tokens=max_tokens,
        )
        if not answer_gen:
            raise RuntimeError("backend.generate returned no generations for the answer")
        answer = answer_gen[0].text

        judge_prompt = _PROMPT_TEMPLATE.format(question=prompt, answer=answer)
        confidence, path = self._whitebox_ptrue(backend, judge_prompt)
        if confidence is None:
            confidence, agreement = self._blackbox_ptrue(backend, judge_prompt)
            raw_scores: dict[str, float] = {
                "p_true": float(confidence),
                "path_is_whitebox": 0.0,
                "blackbox_agreement": float(agreement),
                "n_blackbox_samples": float(self.n_blackbox_samples),
            }
        else:
            raw_scores = {
                "p_true": float(confidence),
                "path_is_whitebox": 1.0,
            }

        return UncertaintyResult(
            answer=answer,
            confidence=float(confidence),
            raw_scores=raw_scores,
            samples=[answer],
            should_refuse=confidence < self.refusal_threshold,
        )

    def _whitebox_ptrue(
        self,
        backend: BackendProto,
        judge_prompt: str,
    ) -> tuple[float | None, str]:
        """Compute p(True) from token log-probabilities if available.

        Runs ``backend.logprobs(judge_prompt, "True")`` and
        ``backend.logprobs(judge_prompt, "False")``. If either call returns
        empty logprobs or raises :class:`NotImplementedError`, returns
        ``(None, "unavailable")`` so the caller can fall back to the
        black-box path.
        """
        try:
            tp = backend.logprobs(judge_prompt, "True")
            fp = backend.logprobs(judge_prompt, "False")
        except NotImplementedError:
            return None, "not-implemented"
        if not tp.logprobs or not fp.logprobs:
            return None, "empty-logprobs"
        lp_true = sum(tp.logprobs)
        lp_false = sum(fp.logprobs)
        # softmax over the two options
        p_true, _ = stable_softmax([lp_true, lp_false])
        return float(p_true), "whitebox"

    def _blackbox_ptrue(
        self,
        backend: BackendProto,
        judge_prompt: str,
    ) -> tuple[float, float]:
        """Fallback: sample the judge and count ``True`` responses."""
        samples = backend.generate(
            judge_prompt,
            n_samples=self.n_blackbox_samples,
            temperature=self.temperature,
            max_tokens=4,
        )
        if not samples:
            return 0.0, 0.0
        votes_true = 0
        votes_false = 0
        for s in samples:
            norm = _normalize(s.text)
            if norm.startswith("true"):
                votes_true += 1
            elif norm.startswith("false"):
                votes_false += 1
        decisive = votes_true + votes_false
        if decisive == 0:
            # model produced no parseable judgment
            return 0.0, 0.0
        p_true = votes_true / decisive
        agreement = decisive / len(samples)
        return float(p_true), float(agreement)


__all__ = ["PTrueEstimator"]
