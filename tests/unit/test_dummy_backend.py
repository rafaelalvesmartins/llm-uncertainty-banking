# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import numpy as np
import pytest

from lub.types import Generation, TokenLogProbs
from lub.wrappers.dummy import DummyBackend


def test_generate_is_deterministic() -> None:
    backend = DummyBackend()
    a = backend.generate("hello world", n_samples=3, temperature=0.7)
    b = backend.generate("hello world", n_samples=3, temperature=0.7)
    assert [g.text for g in a] == [g.text for g in b]
    assert all(isinstance(g, Generation) for g in a)


def test_generate_varies_by_prompt() -> None:
    backend = DummyBackend()
    a = backend.generate("prompt one")
    b = backend.generate("prompt two")
    assert a[0].text != b[0].text


def test_generate_rejects_zero_samples() -> None:
    backend = DummyBackend()
    with pytest.raises(ValueError):
        backend.generate("x", n_samples=0)


def test_logprobs_returns_matching_tokens() -> None:
    backend = DummyBackend()
    result = backend.logprobs("one two three", "answer")
    assert isinstance(result, TokenLogProbs)
    assert result.tokens == ["one", "two", "three"]
    assert len(result.logprobs) == 3


def test_embed_is_unit_norm_and_deterministic() -> None:
    backend = DummyBackend()
    v1 = backend.embed("hello")
    v2 = backend.embed("hello")
    assert np.allclose(v1, v2)
    assert pytest.approx(float(np.linalg.norm(v1)), abs=1e-6) == 1.0
