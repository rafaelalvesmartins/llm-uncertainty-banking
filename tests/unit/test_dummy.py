# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Unit tests for lub.wrappers.dummy.DummyBackend.

Verifies determinism, input validation, and output shape/range invariants
of the deterministic offline backend used as a hermetic test double.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from lub.types import Generation, TokenLogProbs
from lub.wrappers.base import BackendCapability
from lub.wrappers.dummy import _EMBED_DIM, DummyBackend, _seed_from_text


@pytest.fixture
def backend() -> DummyBackend:
    return DummyBackend()


class TestSeedFromText:
    def test_returns_nonnegative_int(self) -> None:
        seed = _seed_from_text("hello")
        assert isinstance(seed, int)
        assert seed >= 0

    def test_is_deterministic(self) -> None:
        assert _seed_from_text("banking") == _seed_from_text("banking")

    def test_different_inputs_yield_different_seeds(self) -> None:
        assert _seed_from_text("a") != _seed_from_text("b")

    def test_empty_string_is_valid(self) -> None:
        seed = _seed_from_text("")
        assert isinstance(seed, int)
        assert seed >= 0


class TestDummyBackendConstruction:
    def test_default_model_id(self) -> None:
        b = DummyBackend()
        assert b.model_id == "dummy-0"

    def test_custom_model_id(self) -> None:
        b = DummyBackend(model_id="dummy-test-7")
        assert b.model_id == "dummy-test-7"

    def test_registry_key(self) -> None:
        assert DummyBackend.REGISTRY_KEY == "dummy"

    def test_capabilities_include_generate_logprobs_embed(self) -> None:
        caps = DummyBackend.CAPABILITIES
        assert caps & BackendCapability.GENERATE
        assert caps & BackendCapability.LOGPROBS
        assert caps & BackendCapability.EMBED


class TestGenerate:
    def test_returns_list_of_generations(self, backend: DummyBackend) -> None:
        out = backend.generate("what is the credit limit?", n_samples=3)
        assert isinstance(out, list)
        assert len(out) == 3
        for g in out:
            assert isinstance(g, Generation)

    def test_single_sample_default(self, backend: DummyBackend) -> None:
        out = backend.generate("hello")
        assert len(out) == 1
        assert out[0].finish_reason == "stop"
        assert out[0].text.startswith("dummy-answer-")

    def test_is_deterministic(self, backend: DummyBackend) -> None:
        a = backend.generate("same prompt", n_samples=2)
        b = backend.generate("same prompt", n_samples=2)
        assert [g.text for g in a] == [g.text for g in b]
        assert [g.logprobs for g in a] == [g.logprobs for g in b]

    def test_different_prompts_produce_different_text(self, backend: DummyBackend) -> None:
        a = backend.generate("prompt A")[0].text
        b = backend.generate("prompt B")[0].text
        assert a != b

    def test_samples_within_one_call_are_distinct(self, backend: DummyBackend) -> None:
        out = backend.generate("collect distinct samples", n_samples=4)
        texts = [g.text for g in out]
        assert len(set(texts)) == len(texts)

    def test_logprobs_are_valid_and_nonpositive(self, backend: DummyBackend) -> None:
        out = backend.generate("any prompt", n_samples=2)
        for g in out:
            assert len(g.logprobs) >= 1
            for lp in g.logprobs:
                assert lp <= 0.0
                assert math.isfinite(lp)

    def test_zero_temperature_yields_single_token(self, backend: DummyBackend) -> None:
        out = backend.generate("deterministic", n_samples=2, temperature=0.0)
        for g in out:
            assert len(g.logprobs) == 1

    def test_n_samples_zero_raises(self, backend: DummyBackend) -> None:
        with pytest.raises(ValueError, match="n_samples must be >= 1"):
            backend.generate("x", n_samples=0)

    def test_n_samples_negative_raises(self, backend: DummyBackend) -> None:
        with pytest.raises(ValueError, match="n_samples must be >= 1"):
            backend.generate("x", n_samples=-3)

    def test_empty_prompt_is_handled(self, backend: DummyBackend) -> None:
        out = backend.generate("", n_samples=1)
        assert len(out) == 1
        assert out[0].text.startswith("dummy-answer-")


class TestLogprobs:
    def test_returns_token_logprobs(self, backend: DummyBackend) -> None:
        result = backend.logprobs("credit risk score", "irrelevant")
        assert isinstance(result, TokenLogProbs)

    def test_tokenization_by_whitespace(self, backend: DummyBackend) -> None:
        result = backend.logprobs("one two three", "ignored")
        assert result.tokens == ["one", "two", "three"]
        assert len(result.logprobs) == 3

    def test_logprob_values_are_constant_and_nonpositive(self, backend: DummyBackend) -> None:
        result = backend.logprobs("alpha beta", "ignored")
        assert all(lp == -1.0 for lp in result.logprobs)

    def test_empty_prompt_yields_empty_arrays(self, backend: DummyBackend) -> None:
        result = backend.logprobs("", "completion")
        assert result.tokens == []
        assert result.logprobs == []

    def test_ignores_completion_argument(self, backend: DummyBackend) -> None:
        a = backend.logprobs("prompt tokens here", "completion-1")
        b = backend.logprobs("prompt tokens here", "completion-2")
        assert a.tokens == b.tokens
        assert a.logprobs == b.logprobs


class TestEmbed:
    def test_returns_ndarray_with_fixed_dim(self, backend: DummyBackend) -> None:
        vec = backend.embed("hello")
        assert isinstance(vec, np.ndarray)
        assert vec.shape == (_EMBED_DIM,)

    def test_is_l2_normalized(self, backend: DummyBackend) -> None:
        vec = backend.embed("any banking question")
        norm = float(np.linalg.norm(vec))
        assert norm == pytest.approx(1.0, abs=1e-9)

    def test_is_deterministic(self, backend: DummyBackend) -> None:
        a = backend.embed("repeatable input")
        b = backend.embed("repeatable input")
        np.testing.assert_array_equal(a, b)

    def test_different_inputs_yield_different_embeddings(self, backend: DummyBackend) -> None:
        a = backend.embed("query one")
        b = backend.embed("query two")
        assert not np.array_equal(a, b)

    def test_empty_string_returns_normalized_vector(self, backend: DummyBackend) -> None:
        vec = backend.embed("")
        assert vec.shape == (_EMBED_DIM,)
        norm = float(np.linalg.norm(vec))
        assert norm == pytest.approx(1.0, abs=1e-9)

    def test_components_are_finite(self, backend: DummyBackend) -> None:
        vec = backend.embed("finiteness check")
        assert np.all(np.isfinite(vec))
