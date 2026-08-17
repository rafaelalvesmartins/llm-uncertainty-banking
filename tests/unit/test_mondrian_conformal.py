# Copyright 2026 Rafael Martins Alves — Apache-2.0

from __future__ import annotations

import pytest

from lub.uncertainty.mondrian_conformal import MondrianConformalEstimator
from lub.wrappers.dummy import DummyBackend


@pytest.fixture
def fitted_estimator(backend: DummyBackend) -> MondrianConformalEstimator:
    est = MondrianConformalEstimator(alpha=0.2)
    calibration = [
        ("q1", "a1", "groupA"),
        ("q2", "a2", "groupA"),
        ("q3", "a3", "groupA"),
        ("q4", "a4", "groupB"),
        ("q5", "a5", "groupB"),
        ("q6", "a6", "groupB"),
    ]
    est.fit(calibration, backend=backend)
    return est


def test_fit_populates_per_group_thresholds(fitted_estimator: MondrianConformalEstimator) -> None:
    assert "groupA" in fitted_estimator.thresholds
    assert "groupB" in fitted_estimator.thresholds
    assert fitted_estimator.n_per_group["groupA"] == 3
    assert fitted_estimator.n_per_group["groupB"] == 3


def test_score_requires_group_kwarg(
    fitted_estimator: MondrianConformalEstimator, backend: DummyBackend
) -> None:
    result = fitted_estimator.score(backend, "q", group="groupA")
    assert 0.0 <= result.confidence <= 1.0
    assert result.answer


def test_score_unknown_group_returns_result(
    fitted_estimator: MondrianConformalEstimator, backend: DummyBackend
) -> None:
    # Unknown groups fall back gracefully rather than raising.
    result = fitted_estimator.score(backend, "q", group="nonexistent")
    assert 0.0 <= result.confidence <= 1.0


def test_requires_fit_before_score(backend: DummyBackend) -> None:
    est = MondrianConformalEstimator(alpha=0.1)
    with pytest.raises(RuntimeError):
        est.score(backend, "q", group="any")


def test_empty_calibration_rejected(backend: DummyBackend) -> None:
    est = MondrianConformalEstimator(alpha=0.1)
    with pytest.raises(ValueError):
        est.fit([], backend=backend)


def test_invalid_alpha_rejected() -> None:
    with pytest.raises(ValueError):
        MondrianConformalEstimator(alpha=0.0)
    with pytest.raises(ValueError):
        MondrianConformalEstimator(alpha=1.0)


def test_different_groups_can_have_different_thresholds(
    fitted_estimator: MondrianConformalEstimator,
) -> None:
    ta = fitted_estimator.thresholds["groupA"]
    tb = fitted_estimator.thresholds["groupB"]
    assert isinstance(ta, float)
    assert isinstance(tb, float)


def test_group_raw_score_stable_across_processes(
    fitted_estimator: MondrianConformalEstimator, backend: DummyBackend
) -> None:
    """The ``group`` audit field must not depend on ``PYTHONHASHSEED``.

    ``hash()`` of a str is salted per process, so ledger rows written by
    different processes would disagree on the same group's fingerprint;
    the field must be a stable digest instead.
    """
    import zlib

    result = fitted_estimator.score(backend, "q", group="groupA")
    assert result.raw_scores["group"] == float(zlib.crc32(b"groupA") % 1000)
