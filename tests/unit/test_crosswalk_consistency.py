# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Consistency tests: crosswalk, mapping, and findings cover all metrics."""

from __future__ import annotations

import pytest

from lub.calibration.metrics import compute_all
from lub.reports.crosswalk import Regime, get_crosswalk, get_crosswalk_for_regime, regimes
from lub.reports.findings import DEFAULT_THRESHOLDS
from lub.reports.mapping import get_iso42001_mapping, get_rmf_mapping

# --- Helpers ---

def _crosswalk_metric_names() -> set[str]:
    return {entry.metric for entry in get_crosswalk()}


def _compute_all_keys() -> set[str]:
    """Keys that compute_all returns (excluding 'n' which is a count)."""
    import numpy as np

    confs = np.array([0.9, 0.8, 0.7, 0.3, 0.2])
    correct = np.array([1, 1, 0, 0, 1], dtype=float)
    result = compute_all(confs, correct, missing=np.array([0, 0, 0, 1, 0]))
    return set(result.keys()) - {"n"}


# --- Tests ---


def test_rmf_mapping_covers_compute_all_keys() -> None:
    """Every metric from compute_all must have an RMF mapping entry."""
    rmf = get_rmf_mapping()
    missing = _compute_all_keys() - set(rmf)
    assert not missing, f"RMF mapping missing: {sorted(missing)}"


def test_iso42001_mapping_covers_compute_all_keys() -> None:
    """Every metric from compute_all must have an ISO 42001 mapping entry."""
    iso = get_iso42001_mapping()
    missing = _compute_all_keys() - set(iso)
    assert not missing, f"ISO 42001 mapping missing: {sorted(missing)}"


def test_crosswalk_covers_compute_all_keys() -> None:
    """Every metric from compute_all must appear in the crosswalk."""
    cw_metrics = _crosswalk_metric_names()
    missing = _compute_all_keys() - cw_metrics
    assert not missing, f"Crosswalk missing: {sorted(missing)}"


def test_findings_thresholds_cover_compute_all_keys() -> None:
    """Every metric from compute_all must have a findings threshold."""
    missing = _compute_all_keys() - set(DEFAULT_THRESHOLDS)
    assert not missing, f"Findings thresholds missing: {sorted(missing)}"


def test_rmf_mapping_subset_of_crosswalk() -> None:
    """Every metric in the RMF mapping should also appear in the crosswalk."""
    rmf_keys = set(get_rmf_mapping())
    cw_metrics = _crosswalk_metric_names()
    missing = rmf_keys - cw_metrics
    assert not missing, f"In RMF mapping but not in crosswalk: {sorted(missing)}"


def test_crosswalk_has_all_five_regimes() -> None:
    """The crosswalk should map at least one metric to each regime."""
    for regime in regimes():
        filtered = get_crosswalk_for_regime(regime)
        assert filtered, f"No crosswalk entries for {regime}"


@pytest.mark.parametrize("regime", list(Regime))
def test_crosswalk_control_ids_unique_per_regime(regime: Regime) -> None:
    """Control IDs should not be duplicated within a single regime."""
    from lub.reports.crosswalk import get_all_controls_for_regime

    controls = get_all_controls_for_regime(regime)
    ids = [c["control_id"] for c in controls]
    assert len(ids) == len(set(ids)), f"Duplicate control IDs in {regime}: {ids}"


def test_every_crosswalk_entry_has_at_least_one_mapping() -> None:
    """No crosswalk entry should have an empty mappings dict."""
    for entry in get_crosswalk():
        assert entry.mappings, f"Metric {entry.metric!r} has no regime mappings"


def test_every_crosswalk_entry_has_trust_dimension() -> None:
    """Every crosswalk entry needs a trust dimension for Holistic AI taxonomy."""
    valid = {"Bias", "Efficacy", "Explainability", "Robustness", "Security"}
    for entry in get_crosswalk():
        assert entry.trust_dimension in valid, (
            f"Metric {entry.metric!r} has invalid trust_dimension "
            f"{entry.trust_dimension!r}; expected one of {valid}"
        )
