"""Tests for lub.agents.adapters.autogen scaffold."""

from __future__ import annotations

import importlib
import importlib.util
from typing import Any
from unittest.mock import MagicMock

import pytest

_HAS_AUTOGEN = importlib.util.find_spec("autogen_agentchat") is not None

pytestmark = pytest.mark.skipif(
    not _HAS_AUTOGEN,
    reason="autogen_agentchat not installed (lub[autogen] extra)",
)


@pytest.fixture
def autogen_module() -> Any:
    """Import lub.agents.adapters.autogen freshly for each test."""
    module = importlib.import_module("lub.agents.adapters.autogen")
    return importlib.reload(module)


@pytest.fixture
def fake_calibrated_agent() -> Any:
    """Return a minimal stand-in for a CalibratedAgent.

    The scaffold raises NotImplementedError before touching the agent,
    so a MagicMock is sufficient for the v0.1 scaffold tests.
    """
    agent = MagicMock()
    agent.prompt_template = "You are a calibrated assistant."
    return agent


def test_module_exposes_to_autogen_agent(autogen_module: Any) -> None:
    """The module must export `to_autogen_agent` in __all__."""
    assert "to_autogen_agent" in autogen_module.__all__
    assert callable(autogen_module.to_autogen_agent)


def test_to_autogen_agent_raises_not_implemented(
    autogen_module: Any, fake_calibrated_agent: Any
) -> None:
    """Scaffold must raise NotImplementedError until v0.3 lands."""
    with pytest.raises(NotImplementedError):
        autogen_module.to_autogen_agent(
            fake_calibrated_agent, name="calibrated_qa"
        )


def test_to_autogen_agent_error_message_mentions_v03(
    autogen_module: Any, fake_calibrated_agent: Any
) -> None:
    """Error message must point users to v0.3 / agents-beta extra."""
    with pytest.raises(NotImplementedError) as exc_info:
        autogen_module.to_autogen_agent(
            fake_calibrated_agent, name="calibrated_qa"
        )
    message = str(exc_info.value)
    assert "v0.3" in message
    assert "agents-beta" in message


def test_to_autogen_agent_accepts_system_message_kwarg(
    autogen_module: Any, fake_calibrated_agent: Any
) -> None:
    """The optional system_message kwarg must be part of the signature."""
    with pytest.raises(NotImplementedError):
        autogen_module.to_autogen_agent(
            fake_calibrated_agent,
            name="calibrated_qa",
            system_message="You are a helpful, calibrated assistant.",
        )


def test_to_autogen_agent_requires_name_kwarg(
    autogen_module: Any, fake_calibrated_agent: Any
) -> None:
    """`name` is keyword-only and required."""
    with pytest.raises(TypeError):
        autogen_module.to_autogen_agent(fake_calibrated_agent)  # type: ignore[call-arg]


def test_to_autogen_agent_name_is_keyword_only(
    autogen_module: Any, fake_calibrated_agent: Any
) -> None:
    """`name` cannot be passed positionally."""
    with pytest.raises(TypeError):
        autogen_module.to_autogen_agent(  # type: ignore[misc]
            fake_calibrated_agent, "calibrated_qa"
        )
