# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the BackendCapability + REQUIRES_CAPABILITIES mechanism.

The ``CapabilityError`` exception class is covered separately by
``test_exceptions.py``; this file exercises the runtime *check* that
raises it — :meth:`Estimator._assert_backend_capabilities` plus the
declarations on the 5 shipping backends and 6 capability-gated
estimators.

These tests pin the contract that protects against the "estimator
silently calls a backend method that raises NotImplementedError mid-
score" failure mode the SR 11-7 auditor would flag.
"""

from __future__ import annotations

from typing import Any

import pytest

from lub.exceptions import CapabilityError
from lub.uncertainty.base import Estimator
from lub.wrappers.base import BackendCapability, ModelBackend
from lub.wrappers.dummy import DummyBackend

# ---------------------------------------------------------------------------
# BackendCapability flag mechanics
# ---------------------------------------------------------------------------


def test_all_capabilities_is_union() -> None:
    """all_capabilities() returns the OR of every defined member."""
    expected = (
        BackendCapability.GENERATE | BackendCapability.LOGPROBS | BackendCapability.EMBED
    )
    assert BackendCapability.all_capabilities() == expected


def test_has_capability_single_flag() -> None:
    backend = DummyBackend(model_id="dummy-model")
    assert backend.has_capability(BackendCapability.GENERATE) is True
    assert backend.has_capability(BackendCapability.LOGPROBS) is True
    assert backend.has_capability(BackendCapability.EMBED) is True


def test_has_capability_composite_requires_all() -> None:
    """Composite flag check is AND, not OR — per the docstring."""
    backend = DummyBackend(model_id="dummy-model")
    composite = BackendCapability.GENERATE | BackendCapability.LOGPROBS
    assert backend.has_capability(composite) is True


def test_has_capability_returns_false_when_missing() -> None:
    """Override CAPABILITIES on a subclass to GENERATE-only and verify."""

    class _GenerateOnly(DummyBackend):
        CAPABILITIES = BackendCapability.GENERATE

    backend = _GenerateOnly(model_id="m")
    assert backend.has_capability(BackendCapability.LOGPROBS) is False
    assert backend.has_capability(BackendCapability.EMBED) is False
    composite = BackendCapability.GENERATE | BackendCapability.LOGPROBS
    assert backend.has_capability(composite) is False


# ---------------------------------------------------------------------------
# Per-backend declarations match the documented contract
# ---------------------------------------------------------------------------


def test_dummy_backend_claims_all_three() -> None:
    assert DummyBackend.CAPABILITIES == BackendCapability.all_capabilities()


def test_anthropic_backend_claims_generate_only() -> None:
    pytest.importorskip("anthropic", reason="anthropic SDK not installed")
    from lub.wrappers.anthropic import AnthropicBackend  # noqa: PLC0415

    assert AnthropicBackend.CAPABILITIES == BackendCapability.GENERATE


def test_openai_backend_claims_generate_and_embed() -> None:
    pytest.importorskip("openai", reason="openai SDK not installed")
    from lub.wrappers.openai import OpenAIBackend  # noqa: PLC0415

    expected = BackendCapability.GENERATE | BackendCapability.EMBED
    assert OpenAIBackend.CAPABILITIES == expected
    assert OpenAIBackend.CAPABILITIES & BackendCapability.LOGPROBS == BackendCapability(0)


def test_vllm_backend_claims_generate_and_logprobs() -> None:
    pytest.importorskip("vllm", reason="vllm not installed")
    from lub.wrappers.vllm import VLLMBackend  # noqa: PLC0415

    expected = BackendCapability.GENERATE | BackendCapability.LOGPROBS
    assert VLLMBackend.CAPABILITIES == expected


# ---------------------------------------------------------------------------
# Estimator REQUIRES_CAPABILITIES + _assert_backend_capabilities
# ---------------------------------------------------------------------------


class _StubEstimator(Estimator):
    """Minimal Estimator subclass for capability-mechanism tests."""

    REGISTRY_KEY = "_stub_capabilities_test"

    def score(self, backend: Any, prompt: str, **kwargs: Any) -> Any:
        raise NotImplementedError  # pragma: no cover — never called in this file


def test_default_requires_capabilities_is_generate_only() -> None:
    """Estimators that don't override the class var only need GENERATE."""
    assert _StubEstimator.REQUIRES_CAPABILITIES == BackendCapability.GENERATE


def test_assert_backend_capabilities_passes_when_satisfied() -> None:
    """No exception when backend supports everything the estimator needs."""
    backend = DummyBackend(model_id="m")
    # _StubEstimator only needs GENERATE; DummyBackend has all three.
    _StubEstimator._assert_backend_capabilities(backend)  # should not raise


def test_assert_backend_capabilities_raises_when_missing() -> None:
    """CapabilityError when one or more required bits are absent."""

    class _NeedsLogprobs(_StubEstimator):
        REGISTRY_KEY = "_needs_logprobs_test"
        REQUIRES_CAPABILITIES = (
            BackendCapability.GENERATE | BackendCapability.LOGPROBS
        )

    class _GenerateOnly(DummyBackend):
        CAPABILITIES = BackendCapability.GENERATE

    backend = _GenerateOnly(model_id="m")
    with pytest.raises(CapabilityError) as excinfo:
        _NeedsLogprobs._assert_backend_capabilities(backend)

    err = excinfo.value
    # Message names estimator, backend, and the missing capability.
    assert "_NeedsLogprobs" in err.message
    assert "_GenerateOnly" in err.message
    assert "LOGPROBS" in err.message

    # Context dict carries structured fields for the audit log.
    assert err.context["estimator"] == "_NeedsLogprobs"
    assert err.context["backend"] == "_GenerateOnly"
    assert "LOGPROBS" in err.context["missing"]
    assert "LOGPROBS" in err.context["required"]
    assert "LOGPROBS" not in err.context["available"]


def test_assert_capabilities_raises_for_multiple_missing() -> None:
    """All missing bits surfaced — not just the first."""

    class _NeedsAll(_StubEstimator):
        REGISTRY_KEY = "_needs_all_test"
        REQUIRES_CAPABILITIES = BackendCapability.all_capabilities()

    class _GenerateOnly(DummyBackend):
        CAPABILITIES = BackendCapability.GENERATE

    backend = _GenerateOnly(model_id="m")
    with pytest.raises(CapabilityError) as excinfo:
        _NeedsAll._assert_backend_capabilities(backend)

    missing = excinfo.value.context["missing"]
    assert "LOGPROBS" in missing
    assert "EMBED" in missing


def test_assert_capabilities_treats_missing_attr_as_generate_only() -> None:
    """Backends predating the capability flag default to GENERATE-only.

    This protects users who subclass ModelBackend in their own code
    (e.g. test doubles) without setting CAPABILITIES — the assert
    treats them as the safe minimum.
    """

    class _NeedsEmbed(_StubEstimator):
        REGISTRY_KEY = "_needs_embed_test"
        REQUIRES_CAPABILITIES = BackendCapability.GENERATE | BackendCapability.EMBED

    class _PreCapabilityDouble:
        """Deliberately does NOT inherit from ModelBackend."""

    with pytest.raises(CapabilityError):
        _NeedsEmbed._assert_backend_capabilities(_PreCapabilityDouble())


# ---------------------------------------------------------------------------
# Live registry: every shipping estimator's REQUIRES_CAPABILITIES is satisfied
# by at least one shipping backend.
# ---------------------------------------------------------------------------


def test_every_estimator_has_at_least_one_compatible_backend() -> None:
    """Sanity: no estimator declares requirements no backend can meet.

    Iterates :class:`Estimator._registry` × :class:`ModelBackend._registry`
    and asserts at least one backend satisfies each estimator's
    REQUIRES_CAPABILITIES. Catches typos like an estimator requiring a
    capability bit that nothing actually provides.
    """
    # Bootstrap both registries.
    import lub.uncertainty  # noqa: F401, PLC0415
    import lub.wrappers  # noqa: F401, PLC0415

    estimators = dict(Estimator._registry)
    backends = dict(ModelBackend._registry)
    assert estimators, "estimator registry empty — bootstrap failed"
    assert backends, "backend registry empty — bootstrap failed"

    incompatible: list[str] = []
    for est_name, est_cls in estimators.items():
        required = est_cls.REQUIRES_CAPABILITIES
        if not any(
            (b_cls.CAPABILITIES & required) == required for b_cls in backends.values()
        ):
            incompatible.append(
                f"{est_name} requires {required.name or required!r} but no backend declares it"
            )

    assert not incompatible, "Estimators with no compatible backend: " + "; ".join(incompatible)
