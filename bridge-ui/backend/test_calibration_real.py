# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""The /calibration ECE is REAL — derived from the labelled intent battery via the
live classifier — not a hardcoded constant.

These tests are the honesty contract for P0-1: they prove the calibration panel's
ECE + reliability table trace to ``server._intent_calibration_samples()`` (real
classifier over real labels), and DISTINGUISH it from server.py's
``_DEMO_SYNTHETIC_METRICS`` placeholders, which remain tagged "synthetic".

Strategy for "is it real, not a constant?": perturb the battery (inject a labelled
case the classifier is guaranteed to get wrong at high confidence) and assert the
ECE *moves*. A hardcoded number would not.

Run from the project root::

    pytest bridge-ui/backend/test_calibration_real.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

from lub.calibration.metrics import expected_calibration_error  # noqa: E402

import server  # noqa: E402

try:
    from backend.routers import calibration as cal  # noqa: E402
except ImportError:
    from routers import calibration as cal  # type: ignore[no-redef]  # noqa: E402


def test_calibration_is_labeled_real_not_synthetic() -> None:
    """The panel declares real provenance, unlike the demo:synthetic placeholders."""
    p = cal.calibration()
    assert p["kind"] == "real"
    # And it does NOT borrow the synthetic source string used by the padding block.
    assert "synthetic" not in p["source"].lower()
    assert server._DEMO_SYNTHETIC_SOURCE not in p["source"]


def test_ece_recomputes_from_the_real_battery() -> None:
    """The endpoint's ECE equals a fresh ECE over the live classifier's verdicts."""
    samples = server._intent_calibration_samples()
    assert samples, "battery must be non-empty"
    confs = [s["confidence"] for s in samples]
    correct = [1.0 if s["correct"] else 0.0 for s in samples]
    expected_ece = round(expected_calibration_error(confs, correct, n_bins=10), 4)
    assert cal.calibration()["ece"] == expected_ece


def test_ece_changes_when_the_battery_is_perturbed() -> None:
    """ECE is data-derived: inject a guaranteed-miss case and it must move.

    A hardcoded constant would return the same number regardless of the battery.
    """
    baseline = cal.calibration()
    assert baseline["kind"] == "real"

    # A query the classifier confidently routes to "balance" (keyword "saldo"),
    # but mislabel its ground truth as "loan" → a guaranteed high-confidence MISS.
    pred, conf = server.classify_intent("qual e o meu saldo")
    assert pred != "loan", "fixture assumption broke; pick a different mislabel"
    assert conf > 0.0

    poison = {"name": "loan", "samples": ["qual e o meu saldo"]}
    original = server._INTENT_CATALOG
    server._INTENT_CATALOG = [*original, poison]
    try:
        perturbed = cal.calibration()
    finally:
        server._INTENT_CATALOG = original

    # The perturbation must change the real signal: one more case, one more miss.
    assert perturbed["n"] == baseline["n"] + 1
    assert len(perturbed["misses"]) == len(baseline["misses"]) + 1
    # ECE is recomputed from the new (confidence, correctness) distribution.
    assert perturbed["ece"] != baseline["ece"]

    # And restoring the battery restores the original ECE — pure function of data.
    assert cal.calibration()["ece"] == baseline["ece"]
