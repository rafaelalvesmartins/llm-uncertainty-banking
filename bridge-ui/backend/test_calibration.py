# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Calibration endpoint — reliability of the intent classifier via lub metrics.

Asserts the endpoint computes real calibration scalars (ECE/Brier/AUROC) over
the catalog's labelled samples and returns a non-empty reliability curve, with
every value inside its valid range.

Run from the project root::

    pytest bridge-ui/backend/test_calibration.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402

try:
    from backend.routers import calibration as cal  # noqa: E402
except ImportError:
    from routers import calibration as cal  # type: ignore[no-redef]  # noqa: E402


def test_calibration_covers_every_catalog_sample() -> None:
    payload = cal.calibration()
    expected_n = sum(len(e.get("samples", [])) for e in server._INTENT_CATALOG)
    assert payload["n"] == expected_n
    assert expected_n > 0


def test_calibration_scalars_in_valid_ranges() -> None:
    p = cal.calibration()
    for key in ("accuracy", "ece", "brier", "sharpness", "auroc"):
        assert p[key] is not None, f"{key} missing"
    assert 0.0 <= p["accuracy"] <= 1.0
    assert 0.0 <= p["ece"] <= 1.0
    assert 0.0 <= p["brier"] <= 1.0
    assert 0.0 <= p["auroc"] <= 1.0
    assert p["sharpness"] >= 0.0


def test_calibration_reliability_curve_is_consistent() -> None:
    p = cal.calibration()
    assert len(p["bins"]) >= 1
    total = 0
    for bin_ in p["bins"]:
        assert 0.0 <= bin_["mean_confidence"] <= 1.0
        assert 0.0 <= bin_["accuracy"] <= 1.0
        assert bin_["lo"] <= bin_["mean_confidence"] <= bin_["hi"]
        assert bin_["count"] >= 1
        # Wilson CI brackets the bin accuracy and stays in [0, 1].
        assert 0.0 <= bin_["accuracy_ci_low"] <= bin_["accuracy"] <= bin_["accuracy_ci_high"] <= 1.0
        total += bin_["count"]
    # every prediction lands in exactly one displayed bin
    assert total == p["n"]


def test_calibration_misses_reference_real_predictions() -> None:
    p = cal.calibration()
    # accuracy and miss list must agree on the count of wrong predictions
    wrong = round((1.0 - p["accuracy"]) * p["n"])
    assert len(p["misses"]) == wrong
    for m in p["misses"]:
        assert m["predicted"] != m["expected"]
