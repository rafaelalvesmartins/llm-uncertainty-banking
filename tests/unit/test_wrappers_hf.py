# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :mod:`lub.wrappers.hf`.

The HuggingFace backend is exercised here without downloading any weights:
the heavy ``AutoModelForCausalLM`` / ``AutoTokenizer`` factories are mocked
and the lazy-load cache is pre-populated with fakes. Real ``torch`` tensors
are used so the shape arithmetic inside ``generate`` / ``logprobs`` /
``embed`` runs end-to-end against an actual tensor backend.
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch

from lub.types import Generation, TokenLogProbs
from lub.wrappers.base import BackendCapability, ModelBackend
from lub.wrappers.hf import HFBackend

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeTokenizerOutput(dict):
    """Tokenizer output: a mapping (so ``**inputs`` works) with ``.to()`` and ``.input_ids``."""

    def __init__(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> None:
        super().__init__(input_ids=input_ids, attention_mask=attention_mask)

    @property
    def input_ids(self) -> torch.Tensor:
        return self["input_ids"]

    @property
    def attention_mask(self) -> torch.Tensor:
        return self["attention_mask"]

    def to(self, _device: str) -> _FakeTokenizerOutput:
        return self


def _make_tokenizer(
    *,
    lengths: list[int] | None = None,
    pad_token_id: int = 0,
) -> MagicMock:
    """Build a mock tokenizer whose ``__call__`` returns tensors of
    explicit token-lengths: the ``i``-th call returns ``lengths[i]`` ids.

    Default is a single 4-token call, enough for ``generate``/``embed``;
    ``logprobs`` should pass ``lengths=[prompt_len, prompt_len + comp_len]``.
    """

    if lengths is None:
        lengths = [4]
    state = {"i": 0}

    tokenizer = MagicMock()
    tokenizer.pad_token_id = pad_token_id
    tokenizer.eos_token_id = pad_token_id

    def _tokenize(_text: str, return_tensors: str = "pt", **_: Any) -> _FakeTokenizerOutput:
        n = lengths[min(state["i"], len(lengths) - 1)]
        state["i"] += 1
        ids = torch.arange(1, n + 1, dtype=torch.long).unsqueeze(0)
        mask = torch.ones_like(ids)
        return _FakeTokenizerOutput(ids, mask)

    tokenizer.side_effect = _tokenize
    tokenizer.decode = MagicMock(side_effect=lambda ids, **_: "tok" if isinstance(ids, list) else "decoded")
    return tokenizer


def _make_model(
    *,
    n_samples: int = 1,
    prompt_len: int = 4,
    new_tokens: int = 3,
    vocab_size: int = 32,
    hidden: int = 8,
) -> MagicMock:
    """Build a mock model that mimics ``AutoModelForCausalLM`` shapes."""

    model = MagicMock()

    # model.generate(...) -> object with .sequences and .scores
    seq = torch.arange(1, prompt_len + new_tokens + 1, dtype=torch.long)
    sequences = seq.unsqueeze(0).repeat(n_samples, 1)
    scores = [torch.randn(n_samples, vocab_size) for _ in range(new_tokens)]
    gen_output = MagicMock()
    gen_output.sequences = sequences
    gen_output.scores = scores
    model.generate = MagicMock(return_value=gen_output)

    # model(input_ids) -> object with .logits  (for logprobs)
    def _forward(full_ids: torch.Tensor | None = None, **kwargs: Any) -> MagicMock:
        if full_ids is None and "input_ids" in kwargs:
            full_ids = kwargs["input_ids"]
        out = MagicMock()
        if full_ids is not None:
            T = int(full_ids.shape[1])
            out.logits = torch.randn(1, T, vocab_size)
            out.hidden_states = [torch.randn(1, T, hidden) for _ in range(2)]
        else:
            out.logits = torch.randn(1, prompt_len, vocab_size)
            out.hidden_states = [torch.randn(1, prompt_len, hidden) for _ in range(2)]
        return out

    model.side_effect = _forward
    model.to = MagicMock(return_value=model)
    model.eval = MagicMock(return_value=model)
    return model


# ---------------------------------------------------------------------------
# Class-level metadata
# ---------------------------------------------------------------------------

def test_registry_key_is_hf() -> None:
    assert HFBackend.REGISTRY_KEY == "hf"


def test_is_modelbackend_subclass() -> None:
    assert issubclass(HFBackend, ModelBackend)


def test_capabilities_declare_generate_logprobs_embed() -> None:
    caps = HFBackend.CAPABILITIES
    assert caps & BackendCapability.GENERATE
    assert caps & BackendCapability.LOGPROBS
    assert caps & BackendCapability.EMBED


def test_module_exports() -> None:
    import lub.wrappers.hf as hf_mod

    assert "HFBackend" in hf_mod.__all__


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

def test_init_stores_model_id_and_starts_unloaded() -> None:
    backend = HFBackend("sshleifer/tiny-gpt2")
    assert backend.model_id == "sshleifer/tiny-gpt2"
    assert backend._model is None
    assert backend._tokenizer is None
    assert backend._device is None


def test_init_accepts_explicit_device() -> None:
    backend = HFBackend("m", device="cpu")
    assert backend._device == "cpu"


def test_init_creates_lock_for_thread_safe_load() -> None:
    backend = HFBackend("m")
    # threading.Lock() returns a _thread.lock instance; verify acquire/release exist.
    assert hasattr(backend._lock, "acquire")
    assert hasattr(backend._lock, "release")


def test_name_property_is_classname_colon_model_id() -> None:
    backend = HFBackend("acme/big-model")
    assert backend.name == "HFBackend:acme/big-model"


# ---------------------------------------------------------------------------
# _load
# ---------------------------------------------------------------------------

def test_load_caches_model_tokenizer_device() -> None:
    backend = HFBackend("m", device="cpu")

    tokenizer = _make_tokenizer()
    model = _make_model()

    with patch("transformers.AutoTokenizer.from_pretrained", return_value=tokenizer) as tk_factory, \
         patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=model) as md_factory:
        m1, t1, d1 = backend._load()
        m2, t2, d2 = backend._load()

    assert m1 is model and t1 is tokenizer and d1 == "cpu"
    assert m2 is model and t2 is tokenizer and d2 == "cpu"
    # Second call must NOT re-download.
    assert tk_factory.call_count == 1
    assert md_factory.call_count == 1


def test_load_sets_pad_token_when_missing() -> None:
    backend = HFBackend("m", device="cpu")

    tokenizer = _make_tokenizer()
    tokenizer.pad_token_id = None
    tokenizer.eos_token_id = 50256
    tokenizer.eos_token = "<|endoftext|>"
    model = _make_model()

    with patch("transformers.AutoTokenizer.from_pretrained", return_value=tokenizer), \
         patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=model):
        backend._load()

    assert tokenizer.pad_token == "<|endoftext|>"


def test_load_auto_selects_cpu_when_cuda_unavailable() -> None:
    backend = HFBackend("m")  # no device passed
    tokenizer = _make_tokenizer()
    model = _make_model()

    with patch("torch.cuda.is_available", return_value=False), \
         patch("transformers.AutoTokenizer.from_pretrained", return_value=tokenizer), \
         patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=model):
        _, _, device = backend._load()

    assert device == "cpu"


def test_load_picks_cuda_when_available() -> None:
    backend = HFBackend("m")
    tokenizer = _make_tokenizer()
    model = _make_model()

    with patch("torch.cuda.is_available", return_value=True), \
         patch("transformers.AutoTokenizer.from_pretrained", return_value=tokenizer), \
         patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=model):
        _, _, device = backend._load()

    assert device == "cuda"
    model.to.assert_called_once_with("cuda")


def test_load_is_thread_safe_against_concurrent_callers() -> None:
    """Many threads racing to load must observe exactly one factory call."""
    backend = HFBackend("m", device="cpu")
    tokenizer = _make_tokenizer()
    model = _make_model()

    barrier = threading.Barrier(8)
    results: list[tuple[Any, Any, str]] = []

    def _go() -> None:
        barrier.wait()
        results.append(backend._load())

    with patch("transformers.AutoTokenizer.from_pretrained", return_value=tokenizer) as tk, \
         patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=model) as md:
        threads = [threading.Thread(target=_go) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert tk.call_count == 1
    assert md.call_count == 1
    assert len(results) == 8
    # Every thread saw the same cached instances.
    assert all(r[0] is model and r[1] is tokenizer and r[2] == "cpu" for r in results)


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------

def _prime(backend: HFBackend, model: MagicMock, tokenizer: MagicMock, device: str = "cpu") -> None:
    """Skip ``_load`` by pre-populating the cache."""
    backend._model = model
    backend._tokenizer = tokenizer
    backend._device = device


def test_generate_rejects_zero_samples() -> None:
    backend = HFBackend("m", device="cpu")
    _prime(backend, _make_model(), _make_tokenizer())
    with pytest.raises(ValueError, match="n_samples must be >= 1"):
        backend.generate("hi", n_samples=0)


def test_generate_rejects_negative_samples() -> None:
    backend = HFBackend("m", device="cpu")
    _prime(backend, _make_model(), _make_tokenizer())
    with pytest.raises(ValueError, match="n_samples must be >= 1"):
        backend.generate("hi", n_samples=-3)


def test_generate_returns_n_generation_objects() -> None:
    backend = HFBackend("m", device="cpu")
    tokenizer = _make_tokenizer(lengths=[4])
    model = _make_model(n_samples=3, prompt_len=4, new_tokens=5)
    _prime(backend, model, tokenizer)

    gens = backend.generate("hello world hello world", n_samples=3, max_tokens=5)

    assert len(gens) == 3
    for g in gens:
        assert isinstance(g, Generation)
        assert isinstance(g.text, str)
        assert g.logprobs is not None
        assert len(g.logprobs) == 5  # one per new token
        assert all(isinstance(lp, float) for lp in g.logprobs)
        assert g.finish_reason == "stop"


def test_generate_passes_sampling_flags_when_multiple_samples() -> None:
    backend = HFBackend("m", device="cpu")
    tokenizer = _make_tokenizer()
    model = _make_model(n_samples=2)
    _prime(backend, model, tokenizer)

    backend.generate("prompt prompt prompt prompt", n_samples=2, temperature=0.5)

    kwargs = model.generate.call_args.kwargs
    assert kwargs["do_sample"] is True
    assert kwargs["temperature"] == pytest.approx(0.5)
    assert kwargs["num_return_sequences"] == 2


def test_generate_uses_greedy_when_single_sample_zero_temperature() -> None:
    backend = HFBackend("m", device="cpu")
    tokenizer = _make_tokenizer()
    model = _make_model(n_samples=1)
    _prime(backend, model, tokenizer)

    backend.generate("prompt prompt prompt prompt", n_samples=1, temperature=0.0)

    kwargs = model.generate.call_args.kwargs
    assert kwargs["do_sample"] is False


def test_generate_clamps_zero_temperature_when_sampling() -> None:
    """``do_sample=True`` with ``temperature=0`` crashes transformers; the
    wrapper must floor it to a tiny positive value to keep the call valid."""
    backend = HFBackend("m", device="cpu")
    tokenizer = _make_tokenizer()
    model = _make_model(n_samples=2)
    _prime(backend, model, tokenizer)

    backend.generate("prompt prompt prompt prompt", n_samples=2, temperature=0.0)

    kwargs = model.generate.call_args.kwargs
    assert kwargs["temperature"] > 0.0


# ---------------------------------------------------------------------------
# logprobs
# ---------------------------------------------------------------------------

def test_logprobs_returns_tokenlogprobs_with_matching_lengths() -> None:
    backend = HFBackend("m", device="cpu")
    tokenizer = _make_tokenizer(lengths=[4, 7])  # prompt=4, prompt+completion=7
    model = _make_model(prompt_len=4)
    _prime(backend, model, tokenizer)

    out = backend.logprobs("a short prompt!!", "the completion text")

    assert isinstance(out, TokenLogProbs)
    # __post_init__ enforces equal length — getting here proves invariant held.
    assert len(out.tokens) == len(out.logprobs)
    assert len(out.tokens) > 0
    assert all(isinstance(lp, float) for lp in out.logprobs)


def test_logprobs_scores_are_finite() -> None:
    backend = HFBackend("m", device="cpu")
    tokenizer = _make_tokenizer(lengths=[4, 7])
    model = _make_model(prompt_len=4)
    _prime(backend, model, tokenizer)

    out = backend.logprobs("a short prompt!!", "the completion text")
    assert all(np.isfinite(lp) for lp in out.logprobs)


# ---------------------------------------------------------------------------
# embed
# ---------------------------------------------------------------------------

def test_embed_returns_float32_1d_array() -> None:
    backend = HFBackend("m", device="cpu")
    tokenizer = _make_tokenizer()
    model = _make_model(prompt_len=4, hidden=8)
    _prime(backend, model, tokenizer)

    vec = backend.embed("an arbitrary text input")

    assert isinstance(vec, np.ndarray)
    assert vec.dtype == np.float32
    assert vec.ndim == 1
    assert vec.shape[0] == 8  # hidden dim


def test_embed_is_finite_under_normal_inputs() -> None:
    backend = HFBackend("m", device="cpu")
    tokenizer = _make_tokenizer()
    model = _make_model(prompt_len=4, hidden=8)
    _prime(backend, model, tokenizer)

    vec = backend.embed("an arbitrary text input")
    assert np.all(np.isfinite(vec))


# ---------------------------------------------------------------------------
# Capability membership behaves correctly through has_capability
# ---------------------------------------------------------------------------

def test_has_capability_for_composite_flag() -> None:
    backend = HFBackend("m")
    assert backend.has_capability(BackendCapability.GENERATE | BackendCapability.LOGPROBS)
    assert backend.has_capability(BackendCapability.EMBED)
