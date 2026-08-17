# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import pytest

from lub.types import TokenLogProbs, UncertaintyResult


def test_token_logprobs_length_mismatch() -> None:
    with pytest.raises(ValueError):
        TokenLogProbs(tokens=["a"], logprobs=[0.0, 0.0])


def test_uncertainty_result_confidence_bounds() -> None:
    with pytest.raises(ValueError):
        UncertaintyResult(answer="x", confidence=1.5)
    with pytest.raises(ValueError):
        UncertaintyResult(answer="x", confidence=-0.1)


def test_uncertainty_result_valid() -> None:
    r = UncertaintyResult(answer="x", confidence=0.5)
    assert r.raw_scores == {}
    assert r.should_refuse is False
