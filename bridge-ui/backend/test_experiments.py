# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Datasets & Experiments endpoint (product v1).

Asserts the labelled battery runs through the live classifier and produces a
reproducible, content-hashed pass/fail report.

Run from the project root::

    pytest bridge-ui/backend/test_experiments.py -v
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402,F401

try:
    from backend.routers import experiments as ex  # noqa: E402
except ImportError:
    from routers import experiments as ex  # type: ignore[no-redef]  # noqa: E402


def test_dataset_lists_labelled_cases() -> None:
    d = ex.datasets()["datasets"][0]
    assert d["id"] == "intent-battery"
    assert d["n_cases"] >= 20
    assert re.fullmatch(r"[0-9a-f]{16}", d["version"])


def test_experiment_scores_pass_fail_and_is_reproducible() -> None:
    a = ex.run_experiment(refresh=True)
    b = ex.run_experiment()  # cached
    assert a["n_cases"] >= 20
    assert 0.0 <= a["accuracy"] <= 1.0
    assert a["n_pass"] <= a["n_cases"]
    assert re.fullmatch(r"[0-9a-f]{64}", a["content_sha256"])
    assert a["content_sha256"] == b["content_sha256"]
    # by_intent totals reconcile with the case count
    assert sum(v["total"] for v in a["by_intent"].values()) == a["n_cases"]
    assert sum(v["pass"] for v in a["by_intent"].values()) == a["n_pass"]


def test_classifier_battery_accuracy_is_strong() -> None:
    # the catalog samples are the classifier's own labelled examples; a healthy
    # classifier should score most of them right. A drop here = a real regression.
    r = ex.run_experiment(refresh=True)
    assert r["accuracy"] >= 0.80, f"battery accuracy regressed: {r['accuracy']} (failures: {r['failures']})"
