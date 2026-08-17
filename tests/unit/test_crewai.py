"""Tests for lub.agents.adapters.crewai module."""

from __future__ import annotations

import importlib.util
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_crewai_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the crewai package appears importable for the adapter module."""
    fake_crewai = MagicMock()
    fake_crewai.__spec__ = MagicMock()
    monkeypatch.setitem(sys.modules, "crewai", fake_crewai)


@pytest.fixture
def crewai_adapter(mock_crewai_available: None):
    """Import the adapter module, reloading to pick up the patched crewai."""
    # Force a fresh import so the top-level spec check runs again.
    sys.modules.pop("lub.agents.adapters.crewai", None)
    from lub.agents.adapters import crewai as adapter

    return adapter


@pytest.fixture
def fake_calibrated_agent() -> Any:
    """Return a stand-in CalibratedAgent (the scaffold never touches it)."""
    agent = MagicMock(name="CalibratedAgent")
    return agent


class TestToCrewAIAgent:
    """Behavior of the to_crewai_agent scaffold."""

    def test_raises_not_implemented(
        self, crewai_adapter: Any, fake_calibrated_agent: Any
    ) -> None:
        """Scaffold raises NotImplementedError until v0.3 wiring lands."""
        with pytest.raises(NotImplementedError):
            crewai_adapter.to_crewai_agent(
                fake_calibrated_agent,
                role="researcher",
                goal="answer questions",
            )

    def test_error_message_mentions_v03(
        self, crewai_adapter: Any, fake_calibrated_agent: Any
    ) -> None:
        """The deferral error message points users at v0.3 / agents-beta."""
        with pytest.raises(NotImplementedError) as exc_info:
            crewai_adapter.to_crewai_agent(
                fake_calibrated_agent,
                role="r",
                goal="g",
                backstory="b",
            )
        message = str(exc_info.value)
        assert "v0.3" in message
        assert "agents-beta" in message

    def test_accepts_optional_backstory(
        self, crewai_adapter: Any, fake_calibrated_agent: Any
    ) -> None:
        """The function signature accepts backstory=None without arg errors."""
        with pytest.raises(NotImplementedError):
            crewai_adapter.to_crewai_agent(
                fake_calibrated_agent,
                role="role",
                goal="goal",
                backstory=None,
            )

    def test_requires_keyword_only_role_and_goal(
        self, crewai_adapter: Any, fake_calibrated_agent: Any
    ) -> None:
        """role and goal must be passed as keyword arguments."""
        with pytest.raises(TypeError):
            crewai_adapter.to_crewai_agent(  # type: ignore[misc]
                fake_calibrated_agent, "role", "goal"
            )


class TestModuleImport:
    """Module-level import behavior."""

    def test_module_exposes_to_crewai_agent(self, crewai_adapter: Any) -> None:
        """Public API surface includes to_crewai_agent."""
        assert hasattr(crewai_adapter, "to_crewai_agent")
        assert callable(crewai_adapter.to_crewai_agent)

    def test_import_fails_without_crewai_extra(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Importing the adapter without the crewai extra raises ImportError."""
        real_find_spec = importlib.util.find_spec

        def fake_find_spec(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "crewai":
                return None
            return real_find_spec(name, *args, **kwargs)

        monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
        monkeypatch.delitem(sys.modules, "crewai", raising=False)
        monkeypatch.delitem(sys.modules, "lub.agents.adapters.crewai", raising=False)

        with pytest.raises(ImportError, match="crewai"):
            importlib.import_module("lub.agents.adapters.crewai")
