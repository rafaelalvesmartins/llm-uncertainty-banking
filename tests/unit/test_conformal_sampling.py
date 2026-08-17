# Copyright 2026 Rafael Martins Alves — Apache-2.0

from __future__ import annotations

import pytest

from lub.uncertainty.conformal_sampling import ConformalSamplingEstimator
from lub.wrappers.dummy import DummyBackend


@pytest.fixture
def calibration_set() -> list[tuple[str, str]]:
    return [
        ("What is CET1?", "Common Equity Tier 1"),
        ("What is LCR?", "Liquidity Coverage Ratio"),
        ("What is NSFR?", "Net Stable Funding Ratio"),
        ("What is RWA?", "Risk-Weighted Assets"),
        ("What is CVA?", "Credit Valuation Adjustment"),
    ]


def test_conformal_sampling_fit_and_score(
    dummy_backend: DummyBackend,
    calibration_set: list[tuple[str, str]],
) -> None:
    est = ConformalSamplingEstimator(n_samples=3)
    est.fit(calibration_set, backend=dummy_backend)
    assert est.tau_admit is not None
    assert est.n_calibration == 5

    result = est.score(dummy_backend, "What is CET1?")
    assert 0.0 <= result.confidence <= 1.0
    assert "n_admitted" in result.raw_scores
    assert "admission_rate" in result.raw_scores
    assert len(result.samples) == 3


def test_conformal_sampling_name() -> None:
    assert ConformalSamplingEstimator.REGISTRY_KEY == "conformal_sampling"


def test_conformal_sampling_rejects_bad_alpha() -> None:
    with pytest.raises(ValueError):
        ConformalSamplingEstimator(alpha=0.0)
    with pytest.raises(ValueError):
        ConformalSamplingEstimator(alpha=1.0)


def test_conformal_sampling_score_before_fit_raises(dummy_backend: DummyBackend) -> None:
    est = ConformalSamplingEstimator()
    with pytest.raises(RuntimeError, match="fit must be called"):
        est.score(dummy_backend, "q")


def test_conformal_sampling_fit_rejects_empty(dummy_backend: DummyBackend) -> None:
    est = ConformalSamplingEstimator()
    with pytest.raises(ValueError):
        est.fit([], backend=dummy_backend)


def test_conformal_sampling_min_admit_fraction(
    dummy_backend: DummyBackend,
    calibration_set: list[tuple[str, str]],
) -> None:
    est = ConformalSamplingEstimator(n_samples=4, min_admit_fraction=0.5)
    assert est.min_admit == 2
    est.fit(calibration_set, backend=dummy_backend)
    result = est.score(dummy_backend, "q")
    if result.raw_scores["n_admitted"] < 2:
        assert result.should_refuse
