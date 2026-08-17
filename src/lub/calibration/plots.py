# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Matplotlib plots for calibration diagnostics.

Kept deliberately small: two figures (reliability diagram, confidence
histogram) and a save helper. No seaborn, no pandas — pure matplotlib so
the library stays lightweight and the plots are reproducible.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import ArrayLike

from lub.calibration.metrics import reliability_curve
from lub.calibration.selective import risk_coverage_curve

if TYPE_CHECKING:
    from matplotlib.figure import Figure


def plot_reliability_diagram(
    confs: ArrayLike,
    correct: ArrayLike,
    n_bins: int = 15,
    title: str | None = None,
) -> Figure:
    """Reliability diagram: empirical accuracy vs mean confidence per bin.

    The diagonal ``y = x`` represents perfect calibration. Points above the
    diagonal indicate under-confidence, below indicate over-confidence.
    Empty bins are skipped.
    """
    import matplotlib.pyplot as plt

    mean_conf, acc = reliability_curve(confs, correct, n_bins=n_bins)
    valid = ~np.isnan(mean_conf)

    fig, ax = plt.subplots(figsize=(5.0, 5.0))
    ax.plot([0.0, 1.0], [0.0, 1.0], linestyle="--", color="gray", label="perfect")
    if valid.any():
        ax.plot(mean_conf[valid], acc[valid], marker="o", color="C0", label="empirical")
        ax.bar(
            mean_conf[valid],
            acc[valid],
            width=1.0 / max(n_bins, 1),
            alpha=0.25,
            color="C0",
            edgecolor="C0",
        )

    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.set_xlabel("Mean confidence")
    ax.set_ylabel("Empirical accuracy")
    ax.set_title(title or "Reliability diagram")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    return fig


def plot_confidence_histogram(
    confs: ArrayLike,
    correct: ArrayLike,
    n_bins: int = 15,
    title: str | None = None,
) -> Figure:
    """Stacked histogram of confidences, split by correct vs incorrect.

    Useful companion to the reliability diagram: shows *where* confidence
    mass concentrates, not just how calibrated it is where it lands.
    """
    import matplotlib.pyplot as plt

    c = np.asarray(confs, dtype=np.float64).ravel()
    y = np.asarray(correct, dtype=np.float64).ravel()
    if c.shape != y.shape:
        raise ValueError(f"confs and correct must have same shape, got {c.shape} vs {y.shape}")

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    correct_mask = y > 0.5

    fig, ax = plt.subplots(figsize=(6.0, 4.0))
    ax.hist(
        [c[correct_mask], c[~correct_mask]],
        bins=edges.tolist(),
        stacked=True,
        color=["C2", "C3"],
        label=["correct", "incorrect"],
        edgecolor="white",
    )
    ax.set_xlim(0.0, 1.0)
    ax.set_xlabel("Confidence")
    ax.set_ylabel("Count")
    ax.set_title(title or "Confidence histogram")
    ax.grid(True, axis="y", linestyle=":", alpha=0.5)
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    return fig


def plot_risk_coverage(
    confs: ArrayLike,
    correct: ArrayLike,
    title: str | None = None,
) -> Figure:
    """Risk-coverage curve: empirical error rate as coverage increases.

    At each coverage level the model retains only its top-confidence
    predictions; the y-axis shows the error rate on the retained set.
    A well-calibrated ranker traces a monotonically non-decreasing curve
    that hugs zero for high-confidence retained sets and rises toward
    the unconditional error rate at full coverage.
    """
    import matplotlib.pyplot as plt

    coverage, risk = risk_coverage_curve(confs, correct)
    fig, ax = plt.subplots(figsize=(6.0, 4.0))
    ax.plot(coverage, risk, color="C0", linewidth=2, label="model")
    baseline = float(risk[-1]) if risk.size else 0.0
    ax.axhline(baseline, color="grey", linestyle="--", linewidth=1, label="no rejection")
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, max(1.0, baseline * 1.1))
    ax.set_xlabel("Coverage")
    ax.set_ylabel("Risk (error rate on kept set)")
    ax.set_title(title or "Risk-coverage curve")
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    return fig


def save_figure(fig: Figure, path: str | Path, dpi: int = 150) -> Path:
    """Save ``fig`` to ``path`` (creating parents) and return the final path."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    return out


__all__ = [
    "plot_confidence_histogram",
    "plot_reliability_diagram",
    "plot_risk_coverage",
    "save_figure",
]
