# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for ``lub.challenge.defaults``."""

from __future__ import annotations

import pytest

from lub.challenge import defaults


class TestReplayDefaults:
    """Tests for replay engine default constants."""

    def test_replay_baseline_threshold_is_high_conviction(self) -> None:
        assert defaults.REPLAY_BASELINE_THRESHOLD == 0.90
        assert 0.0 <= defaults.REPLAY_BASELINE_THRESHOLD <= 1.0

    def test_replay_baseline_threshold_is_float(self) -> None:
        assert isinstance(defaults.REPLAY_BASELINE_THRESHOLD, float)

    def test_replay_score_method_is_confidence(self) -> None:
        assert defaults.REPLAY_SCORE_METHOD == "confidence"

    def test_replay_score_method_is_str(self) -> None:
        assert isinstance(defaults.REPLAY_SCORE_METHOD, str)


class TestEjectionDefaults:
    """Tests for context autopilot ejection constants."""

    def test_ejection_alpha_value(self) -> None:
        assert defaults.EJECTION_ALPHA == 0.5

    def test_ejection_beta_value(self) -> None:
        assert defaults.EJECTION_BETA == 0.2

    def test_ejection_gamma_value(self) -> None:
        assert defaults.EJECTION_GAMMA == 0.3

    def test_ejection_weights_are_positive(self) -> None:
        assert defaults.EJECTION_ALPHA > 0
        assert defaults.EJECTION_BETA > 0
        assert defaults.EJECTION_GAMMA > 0

    def test_ejection_weights_are_floats(self) -> None:
        assert isinstance(defaults.EJECTION_ALPHA, float)
        assert isinstance(defaults.EJECTION_BETA, float)
        assert isinstance(defaults.EJECTION_GAMMA, float)

    def test_ejection_threshold_floor(self) -> None:
        assert defaults.EJECTION_THRESHOLD == 0.5
        assert defaults.EJECTION_THRESHOLD >= 0.0

    def test_ejection_cold_start_is_uninformative(self) -> None:
        assert defaults.EJECTION_COLD_START_USEFULNESS == 0.5
        assert 0.0 <= defaults.EJECTION_COLD_START_USEFULNESS <= 1.0


class TestRecallDefaults:
    """Tests for context autopilot recall constants."""

    def test_recall_k_neighbours_value(self) -> None:
        assert defaults.RECALL_K_NEIGHBOURS == 3

    def test_recall_k_neighbours_is_positive_int(self) -> None:
        assert isinstance(defaults.RECALL_K_NEIGHBOURS, int)
        assert defaults.RECALL_K_NEIGHBOURS > 0

    def test_recall_similarity_threshold_in_unit_interval(self) -> None:
        assert defaults.RECALL_SIMILARITY_THRESHOLD == 0.3
        assert 0.0 <= defaults.RECALL_SIMILARITY_THRESHOLD <= 1.0

    def test_recall_similarity_threshold_is_float(self) -> None:
        assert isinstance(defaults.RECALL_SIMILARITY_THRESHOLD, float)

    def test_headroom_tight_threshold_value(self) -> None:
        assert defaults.HEADROOM_TIGHT_THRESHOLD == 0.15

    def test_headroom_tight_threshold_in_unit_interval(self) -> None:
        assert 0.0 <= defaults.HEADROOM_TIGHT_THRESHOLD <= 1.0


class TestMetaCalibrationDefaults:
    """Tests for meta-calibration constants."""

    def test_meta_calibration_bin_count_is_ten(self) -> None:
        assert defaults.META_CALIBRATION_BIN_COUNT == 10

    def test_meta_calibration_bin_count_is_positive_int(self) -> None:
        assert isinstance(defaults.META_CALIBRATION_BIN_COUNT, int)
        assert defaults.META_CALIBRATION_BIN_COUNT > 0


class TestPublicAPI:
    """Tests for module-level ``__all__`` contract."""

    @pytest.fixture
    def expected_exports(self) -> set[str]:
        return {
            "REPLAY_BASELINE_THRESHOLD",
            "REPLAY_SCORE_METHOD",
            "EJECTION_ALPHA",
            "EJECTION_BETA",
            "EJECTION_GAMMA",
            "EJECTION_THRESHOLD",
            "EJECTION_COLD_START_USEFULNESS",
            "RECALL_K_NEIGHBOURS",
            "RECALL_SIMILARITY_THRESHOLD",
            "HEADROOM_TIGHT_THRESHOLD",
            "META_CALIBRATION_BIN_COUNT",
        }

    def test_all_lists_every_export(self, expected_exports: set[str]) -> None:
        assert set(defaults.__all__) == expected_exports

    def test_all_exports_are_defined(self) -> None:
        for name in defaults.__all__:
            assert hasattr(defaults, name), f"missing export: {name}"

    def test_no_duplicate_entries_in_all(self) -> None:
        assert len(defaults.__all__) == len(set(defaults.__all__))
