# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from lub.calibration.normalizers import (
    BinnedPCCNormalizer,
    IdentityNormalizer,
    IsotonicNormalizer,
    MinMaxNormalizer,
    Normalizer,
    QuantileNormalizer,
    load_normalizer,
)


@pytest.fixture
def toy_data() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(0)
    confs = rng.uniform(0.0, 1.0, size=500)
    correct = (rng.uniform(0.0, 1.0, size=500) < confs).astype(float)
    return confs, correct


def test_identity_round_trip(toy_data: tuple[np.ndarray, np.ndarray], tmp_path: Path) -> None:
    confs, correct = toy_data
    norm = IdentityNormalizer().fit(confs, correct)
    out = norm.transform(confs)
    assert np.allclose(out, np.clip(confs, 0.0, 1.0))

    path = tmp_path / "id.json"
    norm.save(path)
    reloaded = load_normalizer(path)
    assert isinstance(reloaded, IdentityNormalizer)
    assert np.allclose(reloaded.transform(confs), out)


def test_minmax_rescales_to_unit_interval() -> None:
    raw = np.array([2.0, 4.0, 6.0, 8.0, 10.0])
    correct = np.array([0.0, 0.0, 1.0, 1.0, 1.0])
    norm = MinMaxNormalizer().fit(raw, correct)
    out = norm.transform(raw)
    assert out.min() == pytest.approx(0.0)
    assert out.max() == pytest.approx(1.0)


def test_minmax_degenerate_constant_input_survives() -> None:
    raw = np.full(10, 0.42)
    norm = MinMaxNormalizer().fit(raw, np.zeros(10))
    out = norm.transform(raw)
    assert np.all(np.isfinite(out))
    assert np.all(out >= 0.0) and np.all(out <= 1.0)


def test_minmax_json_round_trip(tmp_path: Path) -> None:
    raw = np.array([0.1, 0.5, 0.9])
    norm = MinMaxNormalizer().fit(raw, np.array([0.0, 1.0, 1.0]))
    path = tmp_path / "mm.json"
    norm.save(path)
    loaded = load_normalizer(path)
    assert isinstance(loaded, MinMaxNormalizer)
    assert np.allclose(loaded.transform(raw), norm.transform(raw))


def test_binned_pcc_recovers_bin_accuracy() -> None:
    # Two bins with known empirical accuracy 0.25 and 0.8.
    low = np.full(20, 0.2)
    high = np.full(20, 0.8)
    confs = np.concatenate([low, high])
    correct = np.concatenate(
        [np.concatenate([np.ones(5), np.zeros(15)]), np.concatenate([np.ones(16), np.zeros(4)])]
    )
    norm = BinnedPCCNormalizer(n_bins=5).fit(confs, correct)
    out = norm.transform(np.array([0.2, 0.8]))
    assert out[0] == pytest.approx(0.25, abs=1e-9)
    assert out[1] == pytest.approx(0.8, abs=1e-9)


def test_binned_pcc_rejects_out_of_range_on_fit() -> None:
    with pytest.raises(ValueError):
        BinnedPCCNormalizer().fit(np.array([0.5, 1.5]), np.array([0.0, 1.0]))


def test_binned_pcc_empty_bin_falls_back_to_global() -> None:
    confs = np.array([0.05, 0.95])
    correct = np.array([0.0, 1.0])
    norm = BinnedPCCNormalizer(n_bins=10).fit(confs, correct)
    # Bin 5 is empty → should map to the global accuracy (0.5).
    out = norm.transform(np.array([0.55]))
    assert out[0] == pytest.approx(0.5)


def test_isotonic_monotone_output() -> None:
    rng = np.random.default_rng(1)
    confs = np.sort(rng.uniform(0.0, 1.0, size=200))
    # Correctness rises monotonically with confidence, plus noise.
    probs = np.clip(0.1 + 0.8 * confs, 0.0, 1.0)
    correct = (rng.uniform(0.0, 1.0, size=200) < probs).astype(float)
    norm = IsotonicNormalizer().fit(confs, correct)
    probe = np.linspace(0.0, 1.0, 50)
    out = norm.transform(probe)
    diffs = np.diff(out)
    assert np.all(diffs >= -1e-12)
    assert out.min() >= 0.0
    assert out.max() <= 1.0


def test_isotonic_fit_transform_round_trip(tmp_path: Path) -> None:
    confs = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
    correct = np.array([0.0, 0.0, 1.0, 1.0, 1.0])
    norm = IsotonicNormalizer()
    out = norm.fit_transform(confs, correct)
    path = tmp_path / "iso.json"
    norm.save(path)
    loaded = load_normalizer(path)
    assert isinstance(loaded, IsotonicNormalizer)
    assert np.allclose(loaded.transform(confs), out)


def test_quantile_maps_to_uniform() -> None:
    rng = np.random.default_rng(2)
    raw = rng.standard_normal(1000)
    norm = QuantileNormalizer().fit(raw, np.zeros_like(raw))
    out = norm.transform(raw)
    # Empirical quantile should be ~uniform on [0, 1].
    hist, _ = np.histogram(out, bins=10, range=(0.0, 1.0))
    expected = len(raw) / 10
    assert np.all(np.abs(hist - expected) < expected * 0.3)


@pytest.mark.parametrize(
    "cls",
    [
        IdentityNormalizer,
        MinMaxNormalizer,
        BinnedPCCNormalizer,
        IsotonicNormalizer,
        QuantileNormalizer,
    ],
)
def test_transform_before_fit_raises(cls: type[Normalizer]) -> None:
    """transform() before fit() should raise RuntimeError with a clear message."""
    norm = cls()
    with pytest.raises(RuntimeError, match="fit must be called"):
        norm.transform(np.array([0.5]))


def test_load_normalizer_rejects_unknown_tag(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"type": "nope"}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_normalizer(path)


def test_normalizer_abc_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        Normalizer()  # type: ignore[abstract]
