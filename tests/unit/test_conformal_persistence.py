# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for ConformalEstimator JSON persistence and error paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from lub.uncertainty.conformal import ConformalEstimator
from lub.wrappers.dummy import DummyBackend


def _calibration() -> list[tuple[str, str]]:
    return [
        ("What is CET1?", "Common Equity Tier 1"),
        ("What is LCR?", "Liquidity Coverage Ratio"),
        ("What is NSFR?", "Net Stable Funding Ratio"),
        ("What is RWA?", "Risk-Weighted Assets"),
        ("What is CVA?", "Credit Valuation Adjustment"),
    ]


def test_to_dict_from_dict_round_trip() -> None:
    est = ConformalEstimator(alpha=0.1)
    est.fit(_calibration(), backend=DummyBackend())
    data = est.to_dict()
    assert isinstance(data, dict)
    restored = ConformalEstimator.from_dict(data)
    assert restored.alpha == est.alpha
    assert restored.threshold == est.threshold
    assert restored.n_calibration == est.n_calibration


def test_from_dict_rejects_unknown_type_tag() -> None:
    with pytest.raises(ValueError, match="unexpected type tag"):
        ConformalEstimator.from_dict({"type": "NotConformal", "alpha": 0.1})


def test_save_load_round_trip(tmp_path: Path) -> None:
    est = ConformalEstimator(alpha=0.2)
    est.fit(_calibration(), backend=DummyBackend())
    path = tmp_path / "conformal.json"
    est.save(path)
    assert path.exists()
    restored = ConformalEstimator.load(path)
    assert restored.alpha == 0.2
    assert restored.threshold == est.threshold


def test_unfitted_to_dict_still_serializes() -> None:
    est = ConformalEstimator(alpha=0.1)
    restored = ConformalEstimator.from_dict(est.to_dict())
    assert restored.threshold is None
    assert restored.n_calibration == 0


def test_score_before_fit_raises() -> None:
    est = ConformalEstimator(alpha=0.1)
    with pytest.raises(RuntimeError, match="fit must be called"):
        est.score(DummyBackend(), "q")


def test_fit_rejects_empty_calibration_set() -> None:
    est = ConformalEstimator(alpha=0.1)
    with pytest.raises(ValueError, match="non-empty"):
        est.fit([], backend=DummyBackend())


def test_alpha_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        ConformalEstimator(alpha=0.0)
    with pytest.raises(ValueError):
        ConformalEstimator(alpha=1.0)
