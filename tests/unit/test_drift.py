# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for calibration/drift.py — input drift + CBPE performance estimation."""

from __future__ import annotations

import numpy as np
import pytest

from lub.calibration.drift import (
    CBPEEstimate,
    DriftProfile,
    DriftReport,
    DriftSeverity,
    analyze_drift,
    population_stability_index,
)


def test_drift_profile_from_uniform_confidences() -> None:
    rng = np.random.default_rng(42)
    confs = rng.uniform(0.0, 1.0, size=100)
    profile = DriftProfile.from_confidences(confs)
    assert profile.n == 100
    assert 0.0 <= profile.mean <= 1.0
    assert profile.std > 0.0
    assert profile.q05 < profile.q95
    assert len(profile.histogram_counts) == 20
    assert len(profile.histogram_edges) == 21


def test_drift_profile_from_constant_confidences() -> None:
    confs = np.full(50, 0.7)
    profile = DriftProfile.from_confidences(confs)
    assert profile.mean == pytest.approx(0.7)
    assert profile.std == pytest.approx(0.0, abs=1e-14)
    assert profile.median == pytest.approx(0.7)


def test_drift_profile_empty_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        DriftProfile.from_confidences(np.array([]))


def test_drift_profile_to_dict_roundtrip() -> None:
    confs = np.array([0.1, 0.5, 0.9])
    profile = DriftProfile.from_confidences(confs)
    d = profile.to_dict()
    assert d["n"] == 3
    assert "mean" in d
    assert isinstance(d["histogram_counts"], list)


def test_psi_identical_distributions_near_zero() -> None:
    rng = np.random.default_rng(42)
    confs = rng.uniform(0.0, 1.0, size=500)
    ref = DriftProfile.from_confidences(confs)
    cur = DriftProfile.from_confidences(confs)
    psi = population_stability_index(ref, cur)
    assert psi < 0.01


def test_psi_shifted_distribution_is_positive() -> None:
    rng = np.random.default_rng(42)
    ref_confs = rng.uniform(0.0, 0.5, size=500)
    cur_confs = rng.uniform(0.5, 1.0, size=500)
    ref = DriftProfile.from_confidences(ref_confs)
    cur = DriftProfile.from_confidences(cur_confs)
    psi = population_stability_index(ref, cur)
    assert psi > 0.25  # significant drift


def test_psi_mismatched_bins_raises() -> None:
    ref = DriftProfile.from_confidences(np.array([0.5]), n_bins=10)
    cur = DriftProfile.from_confidences(np.array([0.5]), n_bins=20)
    with pytest.raises(ValueError, match="same number of bins"):
        population_stability_index(ref, cur)


def test_drift_severity_none() -> None:
    s = DriftSeverity.classify(0.05)
    assert s.level == "none"


def test_drift_severity_moderate() -> None:
    s = DriftSeverity.classify(0.15)
    assert s.level == "moderate"


def test_drift_severity_significant() -> None:
    s = DriftSeverity.classify(0.30)
    assert s.level == "significant"


def test_cbpe_estimate_well_calibrated() -> None:
    confs = np.array([0.8, 0.9, 0.7, 0.85, 0.75])
    cbpe = CBPEEstimate.estimate(confs, reference_accuracy=0.80, reference_ece=0.03)
    assert 0.0 <= cbpe.estimated_accuracy <= 1.0
    assert not cbpe.calibration_warning
    assert cbpe.delta == pytest.approx(cbpe.estimated_accuracy - 0.80)


def test_cbpe_estimate_high_ece_warns() -> None:
    confs = np.array([0.8, 0.9])
    cbpe = CBPEEstimate.estimate(confs, reference_accuracy=0.80, reference_ece=0.20)
    assert cbpe.calibration_warning


def test_cbpe_estimate_empty_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        CBPEEstimate.estimate(np.array([]), reference_accuracy=0.8, reference_ece=0.05)


def test_analyze_drift_no_cbpe() -> None:
    rng = np.random.default_rng(0)
    base = rng.uniform(0.0, 1.0, size=1000)
    ref = base[:500]
    cur = base[500:]
    report = analyze_drift(ref, cur)
    assert isinstance(report, DriftReport)
    assert report.cbpe is None
    assert report.drift_severity.level == "none"


def test_analyze_drift_with_cbpe() -> None:
    rng = np.random.default_rng(42)
    ref = rng.uniform(0.0, 1.0, size=100)
    cur = rng.uniform(0.0, 1.0, size=100)
    report = analyze_drift(ref, cur, reference_accuracy=0.75, reference_ece=0.04)
    assert report.cbpe is not None
    assert not report.cbpe.calibration_warning


def test_analyze_drift_detects_significant_shift() -> None:
    rng = np.random.default_rng(42)
    ref = rng.uniform(0.0, 0.3, size=200)
    cur = rng.uniform(0.7, 1.0, size=200)
    report = analyze_drift(ref, cur)
    assert report.drift_severity.level == "significant"


def test_drift_report_to_dict() -> None:
    rng = np.random.default_rng(42)
    ref = rng.uniform(0.0, 1.0, size=50)
    cur = rng.uniform(0.0, 1.0, size=50)
    report = analyze_drift(ref, cur, reference_accuracy=0.80, reference_ece=0.04)
    d = report.to_dict()
    assert "psi" in d
    assert "drift_level" in d
    assert "cbpe" in d
