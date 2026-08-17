# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the HuggingFace backend wrapper.

These tests mock the heavy ``torch`` and ``transformers`` dependencies so
they run quickly in CI. They focus on the contract that the Bridge hub
relies on: deterministic shapes for ``generate`` / ``logprobs`` / ``embed``,
correct lazy-loading behaviour, thread safety, and clean error propagation
when inputs or backends misbehave.
"""

from __future__ import annotations

import sys
import threading
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from lub.types import Generation, TokenLogProbs
from lub.wrappers.base import BackendCapability
from lub.wrappers.hf import _MISSING_DEPS_MSG, HFBackend

# ---------------------------------------------------------------------------
# Fake torch / transformers fixtures
# ---------------------------------------------------------------------------


class _FakeTensor:
    """Minimal stand-in for a ``torch.Tensor`` covering the ops the backend uses."""

    def __init__(self, data: Any, shape: tuple[int, ...] | None = None) -> None:
        self._array = np.asarray(data)
        self._shape = shape if shape is not None else self._array.shape

    @property
    def shape(self) -> tuple[int, ...]:
        return self._shape

    def to(self, device: str) -> _FakeTensor:  # noqa: ARG002 - signature parity
        return self

    def unsqueeze(self, dim: int) -> _FakeTensor:
        return _FakeTensor(np.expand_dims(self._array, axis=dim))

    def float(self) -> _FakeTensor:
        return _FakeTensor(self._array.astype(np.float32))

    def sum(self, dim: int | None = None) -> _FakeTensor:
        if dim is None:
            return _FakeTensor(self._array.sum())
        return _FakeTensor(self._array.sum(axis=dim))

    def clamp(self, min: float = 0.0) -> _FakeTensor:  # noqa: A002 - mirrors torch API
        return _FakeTensor(np.clip(self._array, a_min=min, a_max=None))

    def cpu(self) -> _FakeTensor:
        return self

    def numpy(self) -> np.ndarray[Any, Any]:
        return self._array

    def tolist(self) -> list[Any]:
        return self._array.tolist()

    def item(self) -> Any:
        return self._array.item()

    def __mul__(self, other: _FakeTensor) -> _FakeTensor:
        return _FakeTensor(self._array * other._array)

    def __truediv__(self, other: _FakeTensor) -> _FakeTensor:
        return _FakeTensor(self._array / other._array)

    def __getitem__(self, idx: Any) -> _FakeTensor:
        return _FakeTensor(self._array[idx])


class _FakeInputs(dict):
    """Dict subclass that mimics the HF ``BatchEncoding`` ``.to`` chainability."""

    def to(self, device: str) -> _FakeInputs:  # noqa: ARG002
        return self

    @property
    def input_ids(self) -> _FakeTensor:
        return self["input_ids"]


def _install_fake_transformers(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Install a minimal fake ``transformers`` module into ``sys.modules``.

    Prevents the real ``transformers`` import (which triggers ``torch.__spec__``
    resolution and can blow up when torch is installed but broken).
    """
    fake_tf = ModuleType("transformers")
    fake_tf.AutoTokenizer = MagicMock(name="AutoTokenizer")  # type: ignore[attr-defined]
    fake_tf.AutoModelForCausalLM = MagicMock(name="AutoModelForCausalLM")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "transformers", fake_tf)
    return fake_tf


def _install_fake_torch(monkeypatch: pytest.MonkeyPatch, cuda_available: bool = False) -> ModuleType:
    """Install a minimal fake ``torch`` module into ``sys.modules``."""
    fake_torch = ModuleType("torch")

    class _NoGrad:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *exc: Any) -> None:
            return None

    fake_torch.no_grad = _NoGrad  # type: ignore[attr-defined]
    fake_torch.cuda = SimpleNamespace(is_available=lambda: cuda_available)  # type: ignore[attr-defined]

    def _log_softmax(tensor: _FakeTensor, dim: int = -1) -> _FakeTensor:
        arr = tensor._array  # noqa: SLF001 - test-only fake
        max_v = arr.max(axis=dim, keepdims=True)
        shifted = arr - max_v
        log_sum = np.log(np.exp(shifted).sum(axis=dim, keepdims=True))
        return _FakeTensor(shifted - log_sum)

    fake_torch.log_softmax = _log_softmax  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    return fake_torch


def _make_fake_tokenizer(prompt_len: int = 3, completion_len: int = 4) -> MagicMock:
    tok = MagicMock(name="tokenizer")
    tok.pad_token_id = 0
    tok.eos_token_id = 2
    tok.pad_token = "[PAD]"

    def _tokenize(text: str, **_: Any) -> _FakeInputs:
        # crude length: use prompt_len for the bare prompt and prompt_len+completion_len for combined
        if len(text) > 20:  # prompt + completion
            ids = np.arange(prompt_len + completion_len).reshape(1, -1)
            mask = np.ones((1, prompt_len + completion_len), dtype=np.int64)
        else:
            ids = np.arange(prompt_len).reshape(1, -1)
            mask = np.ones((1, prompt_len), dtype=np.int64)
        return _FakeInputs(
            input_ids=_FakeTensor(ids),
            attention_mask=_FakeTensor(mask),
        )

    tok.side_effect = _tokenize
    tok.decode = MagicMock(side_effect=lambda ids, **_: f"tok-{list(ids)}" if hasattr(ids, "__iter__") else f"tok-{ids}")
    return tok


def _make_fake_model(
    n_samples: int = 1,
    new_tokens: int = 3,
    input_len: int = 3,
    vocab_size: int = 10,
) -> MagicMock:
    model = MagicMock(name="model")

    seq_arr = np.arange(input_len + new_tokens).reshape(1, -1).repeat(n_samples, axis=0)
    scores_per_step = [
        _FakeTensor(np.random.RandomState(step).randn(n_samples, vocab_size))
        for step in range(new_tokens)
    ]
    model.generate.return_value = SimpleNamespace(
        sequences=_FakeTensor(seq_arr),
        scores=scores_per_step,
    )

    def _forward(*_args: Any, output_hidden_states: bool = False, **_kwargs: Any) -> SimpleNamespace:
        # Determine actual input length from positional or keyword args
        if _args:
            actual_len = _args[0].shape[1] if hasattr(_args[0], "shape") else input_len
        elif "input_ids" in _kwargs:
            actual_len = _kwargs["input_ids"].shape[1]
        else:
            actual_len = input_len
        seq_len = input_len + new_tokens if actual_len > input_len else actual_len
        logits = _FakeTensor(np.random.RandomState(0).randn(1, seq_len, vocab_size))
        if output_hidden_states:
            hidden = _FakeTensor(np.random.RandomState(1).randn(1, actual_len, 8))
            return SimpleNamespace(logits=logits, hidden_states=[hidden, hidden])
        return SimpleNamespace(logits=logits)

    model.side_effect = _forward
    model.to = MagicMock(return_value=model)
    model.eval = MagicMock(return_value=model)
    return model


@pytest.fixture
def fake_torch(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    _install_fake_transformers(monkeypatch)
    return _install_fake_torch(monkeypatch, cuda_available=False)


@pytest.fixture
def loaded_backend(fake_torch: ModuleType) -> HFBackend:  # noqa: ARG001 - ensures torch is installed
    backend = HFBackend("test/model", device="cpu")
    tokenizer = _make_fake_tokenizer()
    model = _make_fake_model(n_samples=1, new_tokens=3, input_len=3)
    backend._model = model
    backend._tokenizer = tokenizer
    backend._device = "cpu"
    return backend


# ---------------------------------------------------------------------------
# Initialization & metadata
# ---------------------------------------------------------------------------


class TestHFBackendInit:
    def test_registry_key_is_hf(self) -> None:
        assert HFBackend.REGISTRY_KEY == "hf"

    def test_capabilities_include_generate_logprobs_embed(self) -> None:
        assert BackendCapability.GENERATE in HFBackend.CAPABILITIES
        assert BackendCapability.LOGPROBS in HFBackend.CAPABILITIES
        assert BackendCapability.EMBED in HFBackend.CAPABILITIES

    def test_construction_is_side_effect_free(self) -> None:
        backend = HFBackend("nonexistent/model")
        assert backend.model_id == "nonexistent/model"
        assert backend._model is None
        assert backend._tokenizer is None
        assert backend._device is None

    def test_explicit_device_is_retained_until_load(self) -> None:
        backend = HFBackend("foo", device="cuda:1")
        assert backend._device == "cuda:1"


# ---------------------------------------------------------------------------
# Lazy loading
# ---------------------------------------------------------------------------


class TestLazyLoad:
    def test_load_caches_model_and_tokenizer(self, fake_torch: ModuleType) -> None:  # noqa: ARG002
        tokenizer = _make_fake_tokenizer()
        model = _make_fake_model()
        with patch("transformers.AutoTokenizer.from_pretrained", return_value=tokenizer), patch(
            "transformers.AutoModelForCausalLM.from_pretrained", return_value=model
        ):
            backend = HFBackend("test/model", device="cpu")
            m1, t1, d1 = backend._load()
            m2, t2, d2 = backend._load()
        assert m1 is m2
        assert t1 is t2
        assert d1 == d2 == "cpu"

    def test_load_picks_cuda_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_transformers(monkeypatch)
        _install_fake_torch(monkeypatch, cuda_available=True)
        tokenizer = _make_fake_tokenizer()
        model = _make_fake_model()
        with patch("transformers.AutoTokenizer.from_pretrained", return_value=tokenizer), patch(
            "transformers.AutoModelForCausalLM.from_pretrained", return_value=model
        ):
            backend = HFBackend("test/model")
            _, _, device = backend._load()
        assert device == "cuda"

    def test_load_falls_back_to_cpu(self, fake_torch: ModuleType) -> None:  # noqa: ARG002
        tokenizer = _make_fake_tokenizer()
        model = _make_fake_model()
        with patch("transformers.AutoTokenizer.from_pretrained", return_value=tokenizer), patch(
            "transformers.AutoModelForCausalLM.from_pretrained", return_value=model
        ):
            backend = HFBackend("test/model")
            _, _, device = backend._load()
        assert device == "cpu"

    def test_load_raises_when_dependencies_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "torch", None)
        backend = HFBackend("test/model")
        with pytest.raises(ImportError, match="transformers"):
            backend._load()

    def test_load_sets_pad_token_when_missing(self, fake_torch: ModuleType) -> None:  # noqa: ARG002
        tokenizer = _make_fake_tokenizer()
        tokenizer.pad_token_id = None
        tokenizer.eos_token_id = 2
        model = _make_fake_model()
        with patch("transformers.AutoTokenizer.from_pretrained", return_value=tokenizer), patch(
            "transformers.AutoModelForCausalLM.from_pretrained", return_value=model
        ):
            backend = HFBackend("test/model", device="cpu")
            backend._load()
        # After load, pad_token must have been assigned.
        assert tokenizer.pad_token == tokenizer.eos_token

    def test_concurrent_load_is_thread_safe(self, fake_torch: ModuleType) -> None:  # noqa: ARG002
        tokenizer = _make_fake_tokenizer()
        model = _make_fake_model()
        call_counter = {"n": 0}

        def slow_model_load(*_a: Any, **_kw: Any) -> MagicMock:
            call_counter["n"] += 1
            return model

        with patch("transformers.AutoTokenizer.from_pretrained", return_value=tokenizer), patch(
            "transformers.AutoModelForCausalLM.from_pretrained", side_effect=slow_model_load
        ):
            backend = HFBackend("test/model", device="cpu")
            results: list[tuple[Any, Any, str]] = []

            def worker() -> None:
                results.append(backend._load())

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        assert call_counter["n"] == 1
        assert all(r[0] is model for r in results)


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------


class TestGenerate:
    def test_returns_n_generations(self, fake_torch: ModuleType) -> None:  # noqa: ARG002
        backend = HFBackend("test/model", device="cpu")
        backend._tokenizer = _make_fake_tokenizer()
        backend._model = _make_fake_model(n_samples=3, new_tokens=2, input_len=3)
        backend._device = "cpu"

        gens = backend.generate("How do I open a Bradesco account?", n_samples=3, temperature=0.7)

        assert len(gens) == 3
        assert all(isinstance(g, Generation) for g in gens)
        assert all(g.finish_reason == "stop" for g in gens)

    def test_logprobs_are_attached(self, loaded_backend: HFBackend) -> None:
        gens = loaded_backend.generate("Quero pagar um boleto", n_samples=1, temperature=0.5)
        assert gens[0].logprobs is not None
        assert all(isinstance(lp, float) for lp in gens[0].logprobs)
        # Each step should produce one log-prob, capped by the number of new tokens.
        assert len(gens[0].logprobs) <= 3

    def test_rejects_zero_samples(self, loaded_backend: HFBackend) -> None:
        with pytest.raises(ValueError, match="n_samples must be >= 1"):
            loaded_backend.generate("Olá", n_samples=0)

    def test_rejects_negative_samples(self, loaded_backend: HFBackend) -> None:
        with pytest.raises(ValueError, match="n_samples must be >= 1"):
            loaded_backend.generate("Olá", n_samples=-2)

    def test_greedy_when_single_sample_and_zero_temperature(
        self, fake_torch: ModuleType  # noqa: ARG002
    ) -> None:
        backend = HFBackend("test/model", device="cpu")
        backend._tokenizer = _make_fake_tokenizer()
        backend._model = _make_fake_model(n_samples=1, new_tokens=3, input_len=3)
        backend._device = "cpu"

        backend.generate("ping", n_samples=1, temperature=0.0)
        kwargs = backend._model.generate.call_args.kwargs
        assert kwargs["do_sample"] is False
        assert "temperature" not in kwargs

    def test_sampling_clamps_zero_temperature_floor(self, fake_torch: ModuleType) -> None:  # noqa: ARG002
        # n_samples>1 forces sampling, so temperature is provided and must stay positive.
        backend = HFBackend("test/model", device="cpu")
        backend._tokenizer = _make_fake_tokenizer()
        backend._model = _make_fake_model(n_samples=2, new_tokens=3, input_len=3)
        backend._device = "cpu"
        backend.generate("ping", n_samples=2, temperature=0.0)
        kwargs = backend._model.generate.call_args.kwargs
        assert kwargs["do_sample"] is True
        assert kwargs["temperature"] > 0

    def test_empty_prompt_still_runs(self, loaded_backend: HFBackend) -> None:
        # An empty prompt is a legitimate edge case for the Bridge router (e.g. system-only turns).
        gens = loaded_backend.generate("", n_samples=1)
        assert len(gens) == 1
        assert isinstance(gens[0], Generation)

    def test_propagates_model_runtime_errors(self, loaded_backend: HFBackend) -> None:
        loaded_backend._model.generate.side_effect = RuntimeError("CUDA OOM")
        with pytest.raises(RuntimeError, match="CUDA OOM"):
            loaded_backend.generate("Quero transferir R$ 1000", n_samples=1)

    def test_pii_prompts_are_passed_through_unmodified(self, loaded_backend: HFBackend) -> None:
        # Wrapper layer must not silently mutate inputs — PII redaction belongs to Bridge governance.
        pii_prompt = "CPF 123.456.789-00 quer saldo da conta 0001-12345-6"
        loaded_backend.generate(pii_prompt, n_samples=1)
        # The tokenizer fake records the prompt it received.
        called_with = loaded_backend._tokenizer.call_args[0][0]
        assert called_with == pii_prompt


# ---------------------------------------------------------------------------
# logprobs()
# ---------------------------------------------------------------------------


class TestLogprobs:
    def test_returns_aligned_tokens_and_scores(self, loaded_backend: HFBackend) -> None:
        out = loaded_backend.logprobs("Saldo da conta:", " R$ 1000")
        assert isinstance(out, TokenLogProbs)
        assert len(out.tokens) == len(out.logprobs)
        assert len(out.tokens) > 0
        assert all(isinstance(lp, float) for lp in out.logprobs)

    def test_empty_completion_yields_empty_result(self, loaded_backend: HFBackend) -> None:
        # Same prompt and full string -> no completion tokens.
        out = loaded_backend.logprobs("hello", "")
        assert out.tokens == []
        assert out.logprobs == []

    def test_propagates_model_errors(self, loaded_backend: HFBackend) -> None:
        loaded_backend._model.side_effect = RuntimeError("backend timeout")
        with pytest.raises(RuntimeError, match="backend timeout"):
            loaded_backend.logprobs("prompt", "completion")


# ---------------------------------------------------------------------------
# embed()
# ---------------------------------------------------------------------------


class TestEmbed:
    def test_returns_float32_vector(self, loaded_backend: HFBackend) -> None:
        vec = loaded_backend.embed("Cliente quer cartão de crédito")
        assert isinstance(vec, np.ndarray)
        assert vec.dtype == np.float32
        assert vec.ndim == 1
        assert vec.shape[0] > 0

    def test_handles_empty_string(self, loaded_backend: HFBackend) -> None:
        vec = loaded_backend.embed("")
        assert isinstance(vec, np.ndarray)
        assert vec.dtype == np.float32

    def test_propagates_model_errors(self, loaded_backend: HFBackend) -> None:
        loaded_backend._model.side_effect = RuntimeError("invalid response")
        with pytest.raises(RuntimeError, match="invalid response"):
            loaded_backend.embed("Quero abrir conta")


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


class TestModuleSurface:
    def test_missing_deps_message_mentions_install_command(self) -> None:
        assert "pip install" in _MISSING_DEPS_MSG
        assert "transformers" in _MISSING_DEPS_MSG
        assert "torch" in _MISSING_DEPS_MSG

    def test_all_exports_hf_backend(self) -> None:
        import lub.wrappers.hf as mod

        assert "HFBackend" in mod.__all__
