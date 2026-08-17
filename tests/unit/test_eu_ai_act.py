# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for ``lub.compliance.frameworks.eu_ai_act``."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from lub.compliance.frameworks import eu_ai_act
from lub.reports.crosswalk import ControlMapping, Regime

# --------------------------------------------------------------------------- #
# Module-level constants
# --------------------------------------------------------------------------- #

def test_regime_is_eu_ai_act() -> None:
    """REGIME must point to the EU AI Act enum member."""
    assert eu_ai_act.REGIME is Regime.EU_AI_ACT


def test_crosswalk_key_matches_regime_name() -> None:
    """CROSSWALK_KEY must be the canonical short identifier."""
    assert eu_ai_act.CROSSWALK_KEY == "EU_AI_ACT"
    assert isinstance(eu_ai_act.CROSSWALK_KEY, str)


def test_title_mentions_regulation_and_eu_ai_act() -> None:
    """TITLE must reference both the regulation number and the common name."""
    assert "2024/1689" in eu_ai_act.TITLE
    assert "EU AI Act" in eu_ai_act.TITLE


def test_dunder_all_exposes_public_surface() -> None:
    """__all__ must list exactly the documented public attributes."""
    assert set(eu_ai_act.__all__) == {
        "CROSSWALK_KEY",
        "REGIME",
        "TITLE",
        "get_controls",
    }


# --------------------------------------------------------------------------- #
# get_controls()
# --------------------------------------------------------------------------- #

def test_get_controls_returns_list() -> None:
    """get_controls must return a concrete ``list`` (not a generator/view)."""
    result = eu_ai_act.get_controls()
    assert isinstance(result, list)


def test_get_controls_items_are_control_mappings() -> None:
    """Each element returned by get_controls must satisfy the ControlMapping shape."""
    controls = eu_ai_act.get_controls()
    # ControlMapping is a TypedDict; isinstance() is unsupported at runtime,
    # so verify the structural contract: a dict with the three required str
    # fields. The framework may ship an empty crosswalk -- that is still valid.
    required_keys = {"control_id", "control_title", "description"}
    for item in controls:
        assert isinstance(item, dict)
        assert required_keys <= item.keys(), (
            f"missing required ControlMapping keys: {required_keys - item.keys()}"
        )
        for key in required_keys:
            assert isinstance(item[key], str), f"{key!r} must be str, got {type(item[key]).__name__}"


def test_get_controls_delegates_to_crosswalk() -> None:
    """get_controls must delegate to ``get_all_controls_for_regime``."""
    fake_controls: list[ControlMapping] = []
    with patch(
        "lub.compliance.frameworks.eu_ai_act.get_all_controls_for_regime",
        return_value=iter(fake_controls),
    ) as mocked:
        result = eu_ai_act.get_controls()

    mocked.assert_called_once_with(Regime.EU_AI_ACT)
    assert result == fake_controls
    assert isinstance(result, list)


def test_get_controls_returns_independent_list_each_call() -> None:
    """Mutating the returned list must not affect subsequent calls."""
    first = eu_ai_act.get_controls()
    first_len = len(first)
    first.append("tampered")  # type: ignore[arg-type]
    second = eu_ai_act.get_controls()
    assert len(second) == first_len


def test_get_controls_materializes_iterator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even if the crosswalk yields an iterator, get_controls returns a list."""
    sentinel: list[object] = []

    def _fake(regime: Regime) -> object:
        assert regime is Regime.EU_AI_ACT
        return iter(sentinel)

    monkeypatch.setattr(
        "lub.compliance.frameworks.eu_ai_act.get_all_controls_for_regime",
        _fake,
    )
    result = eu_ai_act.get_controls()
    assert isinstance(result, list)
    assert result == sentinel
