# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Calibration endpoint — reliability of the intent classifier (lub metrics).

The petition's thesis is calibration: a model's stated confidence should match
its empirical accuracy. This endpoint runs the REAL ``lub.calibration`` metrics
(ECE — Guo et al. 2017, Brier, refusal-AUROC, reliability curve) over the intent
classifier's own labelled example queries — every catalog entry carries the
intent it is a sample *of*, which is the ground-truth label. So the dashboard
renders a reliability diagram from a real computation on real labels, not a
canned number.

Honesty: the demo classifier's confidence is heuristic (keyword matches → a few
discrete levels), so the reliability curve is sparse; production would feed
token-logprob confidences. The metrics, labels, and curve here are real.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

if TYPE_CHECKING:
    from types import ModuleType

router = APIRouter()


def _server() -> ModuleType:
    import sys

    mod = sys.modules.get("server") or sys.modules.get("backend.server")
    if mod is not None:
        return mod
    try:
        import server  # type: ignore[no-redef]
    except ImportError:
        from backend import server
    return server


def _build_calibration(s: ModuleType, n_bins: int = 10) -> dict[str, Any]:
    import numpy as np
    from lub.calibration.metrics import (
        brier_score,
        expected_calibration_error,
        refusal_auroc,
        sharpness,
    )

    # Single source of truth shared with the SR 11-7 Outcome Analysis pillar.
    samples = s._intent_calibration_samples()
    confs = [smp["confidence"] for smp in samples]
    correct = [1.0 if smp["correct"] else 0.0 for smp in samples]
    misses = [
        {
            "query": smp["query"],
            "expected": smp["expected"],
            "predicted": smp["predicted"],
            "confidence": round(smp["confidence"], 3),
        }
        for smp in samples
        if not smp["correct"]
    ]

    n = len(confs)
    base = {
        "title": "Intent classifier calibration",
        # Machine-readable provenance: this panel's ECE/reliability come from a
        # REAL computation over the labelled battery — NOT from server.py's
        # `_DEMO_SYNTHETIC_METRICS` placeholders (source "demo:synthetic_placeholder"),
        # which stay in the SR 11-7 view honestly tagged "synthetic".
        "kind": "real",
        "source": "Labelled example queries from the intent catalog (lub.calibration).",
        "method": (
            "For each (query, expected intent) in the catalog, classify_intent → "
            "(predicted, confidence); correct = predicted==expected. Real metrics via lub: "
            "ECE (Guo 2017), Brier, refusal AUROC, sharpness and the reliability curve."
        ),
        "honesty": (
            "Calibration genuinely computed over the catalog's labelled queries "
            "(seeded samples, not production traffic) — the same numbers as the SR 11-7 "
            "Outcome Analysis pillar. The classifier's confidence is heuristic "
            "(discrete levels), so the curve is sparse; production would use token logprobs."
        ),
        "n_bins": n_bins,
        "n": n,
    }
    if n == 0:
        return {**base, "accuracy": None, "ece": None, "brier": None, "sharpness": None, "auroc": None, "bins": [], "misses": []}

    c = np.asarray(confs, dtype=np.float64)
    y = np.asarray(correct, dtype=np.float64)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    # left-closed bins, last bin inclusive of 1.0 (standard ECE binning).
    bidx = np.clip(np.digitize(c, edges) - 1, 0, n_bins - 1)

    bins: list[dict[str, Any]] = []
    for b in range(n_bins):
        m = bidx == b
        cnt = int(m.sum())
        if cnt == 0:
            continue
        # Wilson 95% CI for the bin accuracy (a proportion). With few samples
        # per bin the interval is wide — surfacing that is the honest move.
        p_hat = float(y[m].mean())
        z = 1.96
        denom = 1.0 + z * z / cnt
        center = (p_hat + z * z / (2 * cnt)) / denom
        half = (z / denom) * float(np.sqrt(p_hat * (1 - p_hat) / cnt + z * z / (4 * cnt * cnt)))
        bins.append(
            {
                "lo": round(float(edges[b]), 3),
                "hi": round(float(edges[b + 1]), 3),
                "mean_confidence": round(float(c[m].mean()), 4),
                "accuracy": round(p_hat, 4),
                "accuracy_ci_low": round(max(0.0, center - half), 4),
                "accuracy_ci_high": round(min(1.0, center + half), 4),
                "count": cnt,
            }
        )

    return {
        **base,
        "accuracy": round(float(y.mean()), 4),
        "ece": round(expected_calibration_error(confs, correct, n_bins=n_bins), 4),
        "brier": round(brier_score(confs, correct), 4),
        "sharpness": round(sharpness(confs), 4),
        "auroc": round(refusal_auroc(confs, correct), 4),
        "bins": bins,
        "misses": misses,
    }


@router.get("/calibration")
def calibration() -> dict[str, Any]:
    """Reliability of the intent classifier on its labelled catalog samples."""
    return _build_calibration(_server())


__all__ = ["router"]
