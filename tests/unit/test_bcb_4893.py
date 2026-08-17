# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for lub.compliance.frameworks.bcb_4893."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from lub.compliance.frameworks import bcb_4893
from lub.reports.crosswalk import ControlMapping, Regime


class TestModuleConstants:
    """Verify module-level constants are correctly defined."""

    def test_regime_is_bcb(self) -> None:
        assert bcb_4893.REGIME is Regime.BCB

    def test_crosswalk_key_is_bcb_string(self) -> None:
        assert bcb_4893.CROSSWALK_KEY == "BCB"

    def test_title_matches_resolution(self) -> None:
        assert bcb_4893.TITLE == "BCB Resolução 4.893/2021"

    def test_all_exports_present(self) -> None:
        expected = {"CROSSWALK_KEY", "REGIME", "TITLE", "get_controls"}
        assert set(bcb_4893.__all__) == expected


class TestGetControls:
    """Verify get_controls() delegates correctly and returns a list."""

    def test_returns_list_type(self) -> None:
        result = bcb_4893.get_controls()
        assert isinstance(result, list)

    def test_returns_control_mappings(self) -> None:
        # ControlMapping is a TypedDict; TypedDicts do not support isinstance
        # checks at runtime. Verify the structural contract instead: each item
        # must be a dict carrying the keys declared by ControlMapping.
        result = bcb_4893.get_controls()
        required_keys = {"control_id", "control_title", "description"}
        for item in result:
            assert isinstance(item, dict)
            assert required_keys <= set(item.keys())

    def test_delegates_to_crosswalk_with_bcb_regime(self) -> None:
        with patch(
            "lub.compliance.frameworks.bcb_4893.get_all_controls_for_regime"
        ) as mock_fn:
            mock_fn.return_value = []
            bcb_4893.get_controls()
            mock_fn.assert_called_once_with(Regime.BCB)

    def test_wraps_iterable_into_list(self) -> None:
        sentinel: list[ControlMapping] = []
        with patch(
            "lub.compliance.frameworks.bcb_4893.get_all_controls_for_regime"
        ) as mock_fn:
            mock_fn.return_value = iter(sentinel)
            result = bcb_4893.get_controls()
            assert result == []
            assert isinstance(result, list)

    def test_returns_new_list_each_call(self) -> None:
        first = bcb_4893.get_controls()
        second = bcb_4893.get_controls()
        assert first is not second


@pytest.fixture
def fake_control_mapping() -> ControlMapping:
    """Build a minimal ControlMapping for injection tests."""
    return ControlMapping(
        control_id="BCB-TEST-1",
        title="Test control",
        regime=Regime.BCB,
        description="Synthetic mapping used in unit tests.",
    )


class TestGetControlsWithFixture:
    """Behavioral checks using a fabricated ControlMapping."""

    def test_passes_through_mapping(
        self, fake_control_mapping: ControlMapping
    ) -> None:
        with patch(
            "lub.compliance.frameworks.bcb_4893.get_all_controls_for_regime"
        ) as mock_fn:
            mock_fn.return_value = [fake_control_mapping]
            result = bcb_4893.get_controls()
            assert result == [fake_control_mapping]
