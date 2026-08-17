# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""The air-gapped profile must cover the Bridge connector too.

``AzureOpenAIBackend`` does not derive from ``APIBackend`` — it is a
standalone class satisfying the chatbot's ``LLMBackend`` protocol. The
structural gate in :mod:`lub.governance.local_only` therefore does not
reach it by inheritance, and it has to opt in explicitly. Without this
the profile would be a guarantee with a hole in it: a bank could wire
Azure as the chatbot backend and egress anyway.
"""

from __future__ import annotations

import pytest

from lub.connectors.bridge.integrations.azure_openai import (
    AzureOpenAIBackend,
    AzureOpenAIConfig,
)
from lub.governance.local_only import EgressViolation


def _config() -> AzureOpenAIConfig:
    return AzureOpenAIConfig(
        endpoint="https://example.openai.azure.com",
        api_key="not-a-real-key",
        deployment="gpt-4o-mini",
    )


def test_azure_backend_is_refused_under_the_air_gapped_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUB_LOCAL_ONLY", "1")

    with pytest.raises(EgressViolation, match="AzureOpenAIBackend"):
        AzureOpenAIBackend(config=_config())


def test_the_classifier_does_not_mistake_azure_for_a_local_backend() -> None:
    """A hosted backend outside the APIBackend tree must still read as hosted."""
    from lub.governance.local_only import is_local_backend

    assert AzureOpenAIBackend.LUB_HOSTED is True
    assert is_local_backend(AzureOpenAIBackend) is False


def test_the_profile_is_checked_before_the_sdk_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refusal must not depend on whether the openai package is installed."""
    monkeypatch.setenv("LUB_LOCAL_ONLY", "1")
    monkeypatch.setattr(
        "lub.connectors.bridge.integrations.azure_openai.openai",
        None,
    )

    with pytest.raises(EgressViolation):
        AzureOpenAIBackend(config=_config())
