# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for Monte Carlo dropout estimator.

MCDropoutEstimator requires HFBackend at runtime, but we can test:
1. Initialization validation.
2. The static entropy math (_per_position_probs).
3. The TypeError when a non-HF backend is passed.
"""

from __future__ import annotations

import math

import pytest

from lub.uncertainty.monte_carlo_dropout import MCDropoutEstimator
from lub.wrappers.dummy import DummyBackend

# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def test_mc_dropout_init_defaults() -> None:
    est = MCDropoutEstimator()
    assert est.n_forward_passes == 20
    assert est.temperature == 1.0
    assert est.max_tokens == 64


def test_mc_dropout_init_custom() -> None:
    est = MCDropoutEstimator(n_forward_passes=5, temperature=0.5, max_tokens=128)
    assert est.n_forward_passes == 5
    assert est.temperature == 0.5
    assert est.max_tokens == 128


def test_mc_dropout_rejects_fewer_than_two_passes() -> None:
    with pytest.raises(ValueError, match="n_forward_passes must be >= 2"):
        MCDropoutEstimator(n_forward_passes=1)


def test_mc_dropout_rejects_zero_passes() -> None:
    with pytest.raises(ValueError, match="n_forward_passes must be >= 2"):
        MCDropoutEstimator(n_forward_passes=0)


# ---------------------------------------------------------------------------
# Entropy math (_per_position_probs)
# ---------------------------------------------------------------------------


def test_per_position_probs_empty() -> None:
    h, e = MCDropoutEstimator._per_position_probs([])
    assert h == 0.0
    assert e == 0.0


def test_per_position_probs_all_empty_logprobs() -> None:
    h, e = MCDropoutEstimator._per_position_probs([[], [], []])
    assert h == 0.0
    assert e == 0.0


def test_per_position_probs_single_pass() -> None:
    # One pass with logprob -0.5 => prob ~0.607
    h, e = MCDropoutEstimator._per_position_probs([[-0.5]])
    # Single pass: predictive entropy == expected entropy.
    p = math.exp(-0.5)
    expected_h = -p * math.log(p)
    assert abs(h - expected_h) < 1e-10
    assert abs(e - expected_h) < 1e-10


def test_per_position_probs_two_passes_identical() -> None:
    # Two identical passes => MI ~ 0 (no epistemic uncertainty).
    lps = [[-1.0, -1.0], [-1.0, -1.0]]
    h, e = MCDropoutEstimator._per_position_probs(lps)
    # When passes agree, H should equal E[H], so MI = 0.
    assert abs(h - e) < 1e-10


def test_per_position_probs_normalizes_by_length() -> None:
    # Longer sequence should have same normalized entropy per position.
    lps_short = [[-1.0]]
    lps_long = [[-1.0, -1.0, -1.0, -1.0]]
    h_short, _ = MCDropoutEstimator._per_position_probs(lps_short)
    h_long, _ = MCDropoutEstimator._per_position_probs(lps_long)
    # Same logprobs at each position => same normalized entropy.
    assert abs(h_short - h_long) < 1e-10


def test_per_position_probs_truncates_to_min_length() -> None:
    # Passes of different lengths: truncate to shortest.
    lps = [[-1.0, -2.0, -3.0], [-1.0, -2.0]]
    h, e = MCDropoutEstimator._per_position_probs(lps)
    # Should use only 2 positions (min length).
    assert h > 0.0
    assert e > 0.0


# ---------------------------------------------------------------------------
# Backend type check
# ---------------------------------------------------------------------------


def test_mc_dropout_rejects_dummy_backend() -> None:
    est = MCDropoutEstimator(n_forward_passes=3)
    backend = DummyBackend()
    with pytest.raises(TypeError, match="whitebox backend"):
        est.score(backend, "test prompt")


def test_mc_dropout_registry_key() -> None:
    assert MCDropoutEstimator.REGISTRY_KEY == "mc_dropout"
