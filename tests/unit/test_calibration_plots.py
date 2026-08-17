# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Smoke tests for :mod:`lub.calibration.plots`.

Plotting is notoriously hard to unit-test; we only assert that each
helper returns a valid :class:`matplotlib.figure.Figure` without raising
and that :func:`save_figure` writes a non-empty PNG to disk. Pixel-level
snapshots are intentionally out of scope.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # noqa: E402 — must happen before pyplot import
import numpy as np
from matplotlib.figure import Figure

from lub.calibration.plots import (
    plot_confidence_histogram,
    plot_reliability_diagram,
    plot_risk_coverage,
    save_figure,
)


def _toy() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(0)
    confs = rng.uniform(0.0, 1.0, size=200)
    correct = (rng.uniform(0.0, 1.0, size=200) < confs).astype(float)
    return confs, correct


def test_plot_reliability_diagram_returns_figure() -> None:
    confs, correct = _toy()
    fig = plot_reliability_diagram(confs, correct, n_bins=10, title="toy")
    assert isinstance(fig, Figure)


def test_plot_confidence_histogram_returns_figure() -> None:
    confs, correct = _toy()
    fig = plot_confidence_histogram(confs, correct)
    assert isinstance(fig, Figure)


def test_plot_risk_coverage_returns_figure() -> None:
    confs, correct = _toy()
    fig = plot_risk_coverage(confs, correct, title="risk-coverage smoke")
    assert isinstance(fig, Figure)


def test_plot_risk_coverage_handles_perfect_ranker() -> None:
    confs = np.array([0.1, 0.2, 0.8, 0.9])
    correct = np.array([0.0, 0.0, 1.0, 1.0])
    fig = plot_risk_coverage(confs, correct)
    assert isinstance(fig, Figure)


def test_save_figure_writes_nonempty_png(tmp_path: Path) -> None:
    confs, correct = _toy()
    fig = plot_reliability_diagram(confs, correct)
    out = tmp_path / "nested" / "fig.png"
    saved = save_figure(fig, out)
    assert saved == out
    assert saved.exists()
    assert saved.stat().st_size > 0
