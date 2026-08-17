# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Air-gapped profile: customer prompts must not leave the perimeter.

The gate is structural rather than network-level — every backend that
ships a customer prompt to a third-party endpoint derives from
:class:`~lub.wrappers.api_base.APIBackend`, so refusing to construct one
under ``LUB_LOCAL_ONLY`` fails closed at wiring time instead of at the
first request.
"""

from __future__ import annotations

import pytest

from lub.config import LubConfig
from lub.governance.local_only import EgressViolation, assert_local_only, is_local_backend
from lub.wrappers.anthropic import AnthropicBackend
from lub.wrappers.dummy import DummyBackend
from lub.wrappers.openai import OpenAIBackend

_LOCAL = LubConfig(local_only=True)
_OPEN = LubConfig(local_only=False)


# --- the gate ---------------------------------------------------------------


def test_local_backend_constructs_under_the_air_gapped_profile() -> None:
    assert DummyBackend("dummy-model") is not None


def test_openai_backend_is_refused_under_the_air_gapped_profile() -> None:
    with pytest.raises(EgressViolation):
        OpenAIBackend("gpt-4o-mini", config=_LOCAL)


def test_anthropic_backend_is_refused_under_the_air_gapped_profile() -> None:
    with pytest.raises(EgressViolation):
        AnthropicBackend("claude-3-5-haiku-20241022", config=_LOCAL)


def test_remote_backends_still_work_when_the_profile_is_off() -> None:
    """Default posture is unchanged — this is opt-in, not a breaking change."""
    assert OpenAIBackend("gpt-4o-mini", config=_OPEN) is not None


def test_the_error_names_the_backend_and_the_switch() -> None:
    with pytest.raises(EgressViolation) as excinfo:
        OpenAIBackend("gpt-4o-mini", config=_LOCAL)

    message = str(excinfo.value)
    assert "OpenAIBackend" in message
    assert "LUB_LOCAL_ONLY" in message


def test_the_profile_reads_its_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUB_LOCAL_ONLY", "1")

    with pytest.raises(EgressViolation):
        OpenAIBackend("gpt-4o-mini")


# --- classifying an already-built object graph ------------------------------


def test_is_local_backend_separates_local_from_hosted() -> None:
    assert is_local_backend(DummyBackend("dummy-model")) is True
    assert is_local_backend(OpenAIBackend("gpt-4o-mini", config=_OPEN)) is False


def test_assert_local_only_passes_for_an_all_local_graph() -> None:
    assert_local_only(DummyBackend("a"), DummyBackend("b"))


def test_assert_local_only_rejects_a_mixed_graph() -> None:
    """One hosted backend anywhere in the graph breaks the guarantee."""
    with pytest.raises(EgressViolation, match="OpenAIBackend"):
        assert_local_only(DummyBackend("a"), OpenAIBackend("gpt-4o-mini", config=_OPEN))
