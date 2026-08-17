# Copyright 2026 Rafael Martins Alves — Apache-2.0

from __future__ import annotations

import pytest

from lub.uncertainty.adaptive_conformal import AdaptiveConformalEstimator
from lub.wrappers.dummy import DummyBackend


def test_first_score_has_no_threshold(backend: DummyBackend) -> None:
    est = AdaptiveConformalEstimator(alpha_target=0.1)
    result = est.score(backend, "q1")
    assert result.answer
    assert result.confidence == pytest.approx(0.9)
    assert est.threshold is None


def test_threshold_appears_after_two_scores(backend: DummyBackend) -> None:
    est = AdaptiveConformalEstimator(alpha_target=0.1)
    est.score(backend, "q1")
    est.score(backend, "q2")
    assert est.threshold is not None


def test_update_shifts_alpha(backend: DummyBackend) -> None:
    est = AdaptiveConformalEstimator(alpha_target=0.1, gamma=0.05)
    est.score(backend, "q")
    alpha_before = est.current_alpha
    est.update(covered=False)
    assert est.current_alpha > alpha_before


def test_update_covered_decreases_alpha(backend: DummyBackend) -> None:
    est = AdaptiveConformalEstimator(alpha_target=0.5, gamma=0.1)
    est.score(backend, "q")
    est.update(covered=False)
    alpha_high = est.current_alpha
    est.update(covered=True)
    assert est.current_alpha < alpha_high


def test_window_limits_score_history(backend: DummyBackend) -> None:
    est = AdaptiveConformalEstimator(alpha_target=0.1, window=5)
    for i in range(10):
        est.score(backend, f"q{i}")
    assert len(est._scores) == 5


def test_confidence_in_valid_range(backend: DummyBackend) -> None:
    est = AdaptiveConformalEstimator(alpha_target=0.1)
    for i in range(5):
        result = est.score(backend, f"q{i}")
        assert 0.0 <= result.confidence <= 1.0


def test_invalid_alpha_rejected() -> None:
    with pytest.raises(ValueError):
        AdaptiveConformalEstimator(alpha_target=0.0)
    with pytest.raises(ValueError):
        AdaptiveConformalEstimator(alpha_target=1.0)


def test_invalid_gamma_rejected() -> None:
    with pytest.raises(ValueError):
        AdaptiveConformalEstimator(gamma=0.0)
