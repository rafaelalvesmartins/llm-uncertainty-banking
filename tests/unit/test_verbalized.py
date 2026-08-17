# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

from collections.abc import Iterator

import pytest

from lub.types import Generation
from lub.uncertainty.verbalized import VerbalizedOneShot, VerbalizedTwoShot
from lub.wrappers.dummy import DummyBackend


class _ScriptedBackend(DummyBackend):
    """Backend that returns a scripted sequence of texts in order of call."""

    def __init__(self, texts: list[str]) -> None:
        super().__init__(model_id="scripted")
        self._iter: Iterator[str] = iter(texts)

    def generate(
        self,
        prompt: str,
        n_samples: int = 1,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> list[Generation]:
        try:
            text = next(self._iter)
        except StopIteration:
            text = ""
        return [Generation(text=text, logprobs=[-0.5], finish_reason="stop")]


def test_one_shot_parses_structured_output() -> None:
    backend = _ScriptedBackend(["ANSWER: 4.5%\nCONFIDENCE: 85\n"])
    est = VerbalizedOneShot()
    result = est.score(backend, "What is CET1?")
    assert result.answer == "4.5%"
    assert result.confidence == pytest.approx(0.85)
    assert result.raw_scores["parsed"] == 1.0
    assert result.should_refuse is False


def test_one_shot_clips_above_100() -> None:
    backend = _ScriptedBackend(["ANSWER: x\nCONFIDENCE: 150\n"])
    est = VerbalizedOneShot()
    result = est.score(backend, "q")
    assert result.confidence == pytest.approx(1.0)


def test_one_shot_falls_back_to_zero_on_unparseable() -> None:
    backend = _ScriptedBackend(["no structure here"])
    est = VerbalizedOneShot(refusal_threshold=0.5)
    result = est.score(backend, "q")
    assert result.confidence == 0.0
    assert result.raw_scores["parsed"] == 0.0
    assert result.should_refuse is True


def test_two_shot_uses_two_calls() -> None:
    backend = _ScriptedBackend(["4.5%", "80"])
    est = VerbalizedTwoShot()
    result = est.score(backend, "q")
    assert result.answer == "4.5%"
    assert result.confidence == pytest.approx(0.80)
    assert result.raw_scores["parsed"] == 1.0


def test_two_shot_extracts_integer_from_noisy_rating() -> None:
    backend = _ScriptedBackend(["answer text", "I would say about 65 out of 100"])
    est = VerbalizedTwoShot()
    result = est.score(backend, "q")
    assert result.confidence == pytest.approx(0.65)


def test_invalid_refusal_threshold_rejected() -> None:
    with pytest.raises(ValueError):
        VerbalizedOneShot(refusal_threshold=2.0)
    with pytest.raises(ValueError):
        VerbalizedTwoShot(refusal_threshold=-0.1)
