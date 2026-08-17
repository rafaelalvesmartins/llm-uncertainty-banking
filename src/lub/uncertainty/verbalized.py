# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Verbalized-confidence estimators (one-shot and two-shot).

These are purely black-box estimators that ask the model to self-rate
its confidence on a 0-100 scale. They work against any backend
including hosted APIs (OpenAI, Anthropic) where token log-probabilities
are unavailable or restricted, which is a coverage gap every pure
logprob-based estimator has.

Both variants are inspired by the verbalized-confidence estimators in
LM-Polygraph (github.com/IINemo/lm-polygraph, MIT). LUB re-implements
them from the published prompting pattern rather than copying code, to
keep the dependency surface clean.

The published literature on verbalized confidence shows that self-rating
is systematically over-confident on hard questions — treat the scores as
a diagnostic signal that complements sampling-based methods, not as a
substitute for them.

References:
    Tian, K., Mitchell, E., Yao, H., Manning, C. D., & Finn, C. (2023).
    *Just Ask for Calibration: Strategies for Eliciting Calibrated
    Confidence Scores from Language Models Fine-Tuned with Human
    Feedback.* EMNLP 2023. arXiv:2305.14975.

    Lin, S., Hilton, J., & Evans, O. (2022). *Teaching Models to Express
    Their Uncertainty in Words.* TMLR. arXiv:2205.14334.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty.base import Estimator

_LOG = structlog.get_logger("lub.uncertainty.verbalized")

_ONE_SHOT_TEMPLATE = (
    "{prompt}\n\n"
    "Respond with a single line of the form:\n"
    "ANSWER: <your answer>\n"
    "CONFIDENCE: <integer from 0 to 100>\n"
)

_TWO_SHOT_ANSWER_TEMPLATE = "{prompt}"
_TWO_SHOT_RATE_TEMPLATE = (
    "Question: {prompt}\n"
    "Proposed answer: {answer}\n\n"
    "On a scale of 0 to 100, how confident are you that the proposed "
    "answer is correct? Respond with a single integer only."
)

_ANSWER_RE = re.compile(r"ANSWER\s*:\s*(.+)", re.IGNORECASE)
_CONF_RE = re.compile(r"CONFIDENCE\s*:\s*(\d{1,3})", re.IGNORECASE)
_INT_RE = re.compile(r"\b(\d{1,3})\b")


def _clip_percent(value: int) -> float:
    """Clip an integer percent to the closed unit interval [0.0, 1.0]."""
    if value < 0:
        return 0.0
    if value > 100:
        return 1.0
    return value / 100.0


def _parse_one_shot(text: str) -> tuple[str, float | None]:
    """Extract the answer and (optional) confidence from a one-shot reply."""
    answer_match = _ANSWER_RE.search(text)
    conf_match = _CONF_RE.search(text)
    answer = answer_match.group(1).strip() if answer_match else text.strip()
    if conf_match:
        return answer, _clip_percent(int(conf_match.group(1)))
    return answer, None


def _parse_two_shot_rating(text: str) -> float | None:
    """Extract the first integer rating from a two-shot rating reply."""
    match = _INT_RE.search(text)
    if match is None:
        return None
    return _clip_percent(int(match.group(1)))


class VerbalizedOneShot(Estimator):
    """Ask the model for answer + confidence in a single call.

    Cheapest verbalized variant: one generation, one parse. The prompt
    forces a fixed ``ANSWER: / CONFIDENCE:`` layout so the parser never
    has to guess.
    """

    REGISTRY_KEY = "verbalized_1s"

    def __init__(self, refusal_threshold: float = 0.5) -> None:
        """Initialize with the refusal threshold applied to verbalized confidence."""
        self.refusal_threshold = self._validate_threshold(refusal_threshold)

    def score(
        self,
        backend: BackendProto,
        prompt: str,
        **kwargs: Any,
    ) -> UncertaintyResult:
        """Run a single greedy generation and parse the self-rated confidence."""
        max_tokens = int(kwargs.get("max_tokens", 256))
        wrapped = _ONE_SHOT_TEMPLATE.format(prompt=prompt)
        generations = self._require_generations(
            backend.generate(
                wrapped,
                n_samples=1,
                temperature=0.0,
                max_tokens=max_tokens,
            )
        )
        text = generations[0].text
        answer, confidence = _parse_one_shot(text)
        parsed = confidence is not None
        if confidence is None:
            confidence = 0.0

        return UncertaintyResult(
            answer=answer,
            confidence=float(confidence),
            raw_scores={
                "verbalized_confidence": float(confidence),
                "parsed": 1.0 if parsed else 0.0,
            },
            samples=[text],
            should_refuse=confidence < self.refusal_threshold,
        )


class VerbalizedTwoShot(Estimator):
    """Answer first, then rate. Two backend calls, cleaner separation.

    Two-shot is more expensive but avoids the answer being conditioned
    on the confidence-request prompt, which can bias the model toward
    hedging. Use this when the one-shot parse rate is unreliable.
    """

    REGISTRY_KEY = "verbalized_2s"

    def __init__(self, refusal_threshold: float = 0.5) -> None:
        """Initialize with the refusal threshold applied to verbalized confidence."""
        self.refusal_threshold = self._validate_threshold(refusal_threshold)

    def score(
        self,
        backend: BackendProto,
        prompt: str,
        **kwargs: Any,
    ) -> UncertaintyResult:
        """Generate the answer, then ask the model to rate its own correctness."""
        max_tokens = int(kwargs.get("max_tokens", 256))

        answer_gens = self._require_generations(
            backend.generate(
                _TWO_SHOT_ANSWER_TEMPLATE.format(prompt=prompt),
                n_samples=1,
                temperature=0.0,
                max_tokens=max_tokens,
            )
        )
        answer = answer_gens[0].text.strip()

        rate_gens = backend.generate(
            _TWO_SHOT_RATE_TEMPLATE.format(prompt=prompt, answer=answer),
            n_samples=1,
            temperature=0.0,
            max_tokens=16,
        )
        rating_text = rate_gens[0].text if rate_gens else ""
        confidence = _parse_two_shot_rating(rating_text)
        parsed = confidence is not None
        if confidence is None:
            confidence = 0.0

        return UncertaintyResult(
            answer=answer,
            confidence=float(confidence),
            raw_scores={
                "verbalized_confidence": float(confidence),
                "parsed": 1.0 if parsed else 0.0,
            },
            samples=[answer, rating_text],
            should_refuse=confidence < self.refusal_threshold,
        )


__all__ = ["VerbalizedOneShot", "VerbalizedTwoShot"]
