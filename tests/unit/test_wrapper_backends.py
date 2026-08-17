# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Smoke tests for all wrapper backends — registry, init, protocol compliance."""

from __future__ import annotations

import importlib.util

import pytest

from lub.wrappers.base import ModelBackend, get_backend_cls

# ---------------------------------------------------------------------------
# Registry: every backend is discoverable by its REGISTRY_KEY
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "key",
    [
        "dummy",
        "hf",
        "openai",
        "anthropic",
        pytest.param(
            "vllm",
            marks=pytest.mark.skipif(
                importlib.util.find_spec("vllm") is None,
                reason="vllm extra not installed",
            ),
        ),
    ],
)
def test_backend_resolvable_by_registry_key(key: str) -> None:
    cls = get_backend_cls(key)
    assert issubclass(cls, ModelBackend)
    assert cls.REGISTRY_KEY == key


def test_unknown_backend_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unknown backend"):
        get_backend_cls("nonexistent_backend_xyz")


# ---------------------------------------------------------------------------
# DummyBackend: full behavioral test (no external deps)
# ---------------------------------------------------------------------------

def test_dummy_backend_full_cycle() -> None:
    from lub.wrappers.dummy import DummyBackend

    backend = DummyBackend("dummy-test")
    assert backend.model_id == "dummy-test"

    gens = backend.generate("hello", n_samples=2)
    assert len(gens) == 2
    for g in gens:
        assert g.text
        assert g.logprobs is not None

    lps = backend.logprobs("hello world", "foo")
    assert len(lps.tokens) == len(lps.logprobs)

    vec = backend.embed("test")
    assert vec.shape == (8,)


# ---------------------------------------------------------------------------
# API backends: init validation (no network calls)
# ---------------------------------------------------------------------------

def test_openai_backend_class_exists() -> None:
    from lub.wrappers.openai import OpenAIBackend

    assert OpenAIBackend.REGISTRY_KEY == "openai"
    assert issubclass(OpenAIBackend, ModelBackend)


def test_anthropic_backend_class_exists() -> None:
    from lub.wrappers.anthropic import AnthropicBackend

    assert AnthropicBackend.REGISTRY_KEY == "anthropic"
    assert issubclass(AnthropicBackend, ModelBackend)


def test_hf_backend_class_exists() -> None:
    from lub.wrappers.hf import HFBackend

    assert HFBackend.REGISTRY_KEY == "hf"
    assert issubclass(HFBackend, ModelBackend)


def test_vllm_backend_class_exists() -> None:
    from lub.wrappers.vllm import VLLMBackend

    assert VLLMBackend.REGISTRY_KEY == "vllm"
    assert issubclass(VLLMBackend, ModelBackend)


# ---------------------------------------------------------------------------
# Protocol compliance: all backends have the required methods
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "key",
    ["dummy", "hf", "openai", "anthropic"],
)
def test_backend_has_protocol_methods(key: str) -> None:
    cls = get_backend_cls(key)
    assert hasattr(cls, "generate")
    assert hasattr(cls, "logprobs")
    assert hasattr(cls, "embed")
    assert callable(getattr(cls, "generate"))
    assert callable(getattr(cls, "logprobs"))
    assert callable(getattr(cls, "embed"))
