# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Plot the cost-vs-risk Pareto frontier of the cascaded router.

Takes the JSON produced by ``run_cascaded_router.py`` and sweeps the
per-tier confidence threshold grid to produce a scatter of
(expected_cost_per_query, risk_at_fixed_coverage) points, marks the
Pareto-dominant subset, and writes a PNG.

Usage
-----
    python benchmarks/scripts/plot_cascaded_pareto.py \\
        --input benchmarks/results/cascaded/run.json \\
        --out docs/figures/figure_3_cascaded_pareto.png
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless backend for CI
import matplotlib.pyplot as plt  # noqa: E402


@dataclass(frozen=True)
class _Point:
    threshold: float
    cost: float
    risk: float
    coverage: float


def _is_correct(predicted: str | None, gold: str | None) -> bool:
    if predicted is None or gold is None:
        return False
    return predicted.strip().lower() == str(gold).strip().lower()


def _sweep_thresholds(
    rows: list[dict[str, object]],
    grid: list[float],
) -> list[_Point]:
    """For each threshold, compute (cost, risk, coverage).

    - *Cost* is the mean ``total_cost`` over rows whose *escalation
      path* stayed cheap enough given the threshold (a synthetic model
      — the real cost is what the router produced).
    - *Risk* is 1 - accuracy over the *covered* subset
      (confidence >= threshold).
    - *Coverage* is the fraction of rows with confidence >= threshold.
    """
    points: list[_Point] = []
    for t in grid:
        covered_correct = 0
        covered = 0
        total_cost = 0.0
        for row in rows:
            routed = row.get("routed", {}) or {}
            final = routed.get("final") or {}
            conf = float(final.get("confidence", 0.0) or 0.0)
            if conf < t:
                continue
            covered += 1
            total_cost += float(routed.get("total_cost", 0.0) or 0.0)
            predicted = str(final.get("answer", "") or "")
            gold = row.get("ground_truth")
            gold_str = None if gold is None else str(gold)
            if _is_correct(predicted, gold_str):
                covered_correct += 1
        if covered == 0:
            continue
        accuracy = covered_correct / covered
        risk = 1.0 - accuracy
        cost = total_cost / covered
        coverage = covered / max(1, len(rows))
        points.append(_Point(threshold=t, cost=cost, risk=risk, coverage=coverage))
    return points


def _pareto_front(points: list[_Point]) -> list[_Point]:
    """Return the minimum-cost / minimum-risk Pareto front."""
    front: list[_Point] = []
    for p in sorted(points, key=lambda q: (q.cost, q.risk)):
        if not front or p.risk < front[-1].risk:
            front.append(p)
    return front


def _default_grid() -> list[float]:
    # Avoid 0 and 1 — they degenerate to "cover everything" and
    # "cover nothing" respectively.
    return [round(0.05 + 0.05 * i, 2) for i in range(19)]


def _read_rows(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as f:
        blob = json.load(f)
    rows = blob.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"expected 'rows' list in {path}, got {type(rows).__name__}")
    return rows


def plot_pareto(
    rows: list[dict[str, object]],
    out: Path,
    grid: list[float] | None = None,
    title: str = "Cost vs risk — cascaded router",
) -> list[_Point]:
    """Compute and plot the Pareto frontier. Returns the front points."""
    grid = grid or _default_grid()
    points = _sweep_thresholds(rows, grid)
    front = _pareto_front(points)

    fig, ax = plt.subplots(figsize=(7, 4.5))
    if points:
        ax.scatter(
            [p.cost for p in points],
            [p.risk for p in points],
            c="tab:gray",
            alpha=0.45,
            s=30,
            label="all thresholds",
        )
    if front:
        ax.plot(
            [p.cost for p in front],
            [p.risk for p in front],
            color="tab:red",
            marker="o",
            linewidth=1.5,
            label="Pareto front",
        )
    ax.set_xlabel("Expected cost per covered query (USD)")
    ax.set_ylabel("Risk (1 − accuracy on covered subset)")
    ax.set_title(title)
    ax.grid(True, linestyle=":", alpha=0.5)
    # If points exist, pad axis ranges a little so markers are inside.
    if points:
        xs = [p.cost for p in points]
        ys = [p.risk for p in points]
        ax.set_xlim(max(0.0, min(xs) * 0.9), max(xs) * 1.1 + 1e-9)
        ax.set_ylim(max(0.0, min(ys) - 0.02), min(1.0, max(ys) + 0.05))
    ax.legend(loc="best")
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return front


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--title", default="Cost vs risk — cascaded router")
    args = parser.parse_args()

    rows = _read_rows(args.input)
    front = plot_pareto(rows, args.out, title=args.title)
    if not front:
        print(f"[warn] no Pareto points produced from {args.input}")
        return
    print(f"wrote {args.out} with {len(front)} Pareto point(s):")
    for p in front:
        print(
            f"  threshold={p.threshold:.2f}  cost={p.cost:.4f}  "
            f"risk={p.risk:.3f}  coverage={p.coverage:.2%}"
        )
    # Guard against NaNs leaking into CI artifacts.
    for p in front:
        if math.isnan(p.cost) or math.isnan(p.risk):
            raise RuntimeError(f"NaN in Pareto point: {p}")


if __name__ == "__main__":
    main()
