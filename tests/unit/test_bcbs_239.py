# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for :mod:`lub.compliance.frameworks.bcbs_239`."""

from __future__ import annotations

from unittest.mock import patch

from lub.compliance.frameworks import bcbs_239
from lub.reports.crosswalk import ControlMapping, Regime


class TestModuleConstants:
    def test_regime_is_bcbs(self) -> None:
        assert bcbs_239.REGIME is Regime.BCBS

    def test_crosswalk_key_is_bcbs_string(self) -> None:
        assert bcbs_239.CROSSWALK_KEY == "BCBS"

    def test_title_mentions_bcbs_239(self) -> None:
        assert "BCBS 239" in bcbs_239.TITLE

    def test_title_mentions_risk_data_aggregation(self) -> None:
        assert "risk data aggregation" in bcbs_239.TITLE.lower()

    def test_all_exports_expected_names(self) -> None:
        assert set(bcbs_239.__all__) == {
            "CROSSWALK_KEY",
            "REGIME",
            "TITLE",
            "get_controls",
        }


class TestGetControls:
    def test_returns_list(self) -> None:
        result = bcbs_239.get_controls()
        assert isinstance(result, list)

    def test_returns_control_mappings(self) -> None:
        # ControlMapping is a TypedDict; TypedDicts do not support isinstance
        # checks at runtime. Verify the structural contract instead: each item
        # must be a dict carrying the keys declared by ControlMapping.
        result = bcbs_239.get_controls()
        required_keys = {"control_id", "control_title", "description"}
        for item in result:
            assert isinstance(item, dict)
            assert required_keys <= set(item.keys())

    def test_delegates_to_crosswalk_with_bcbs_regime(self) -> None:
        with patch.object(
            bcbs_239, "get_all_controls_for_regime", return_value=[]
        ) as mock_get:
            bcbs_239.get_controls()
            mock_get.assert_called_once_with(Regime.BCBS)

    def test_returns_independent_list_copy(self) -> None:
        fake_mapping = ControlMapping.__new__(ControlMapping)
        backing = [fake_mapping]
        with patch.object(
            bcbs_239, "get_all_controls_for_regime", return_value=backing
        ):
            result = bcbs_239.get_controls()
            result.clear()
            assert backing == [fake_mapping]

    def test_returns_all_items_from_crosswalk(self) -> None:
        sentinel_a = ControlMapping.__new__(ControlMapping)
        sentinel_b = ControlMapping.__new__(ControlMapping)
        with patch.object(
            bcbs_239,
            "get_all_controls_for_regime",
            return_value=iter([sentinel_a, sentinel_b]),
        ):
            result = bcbs_239.get_controls()
            assert result == [sentinel_a, sentinel_b]
