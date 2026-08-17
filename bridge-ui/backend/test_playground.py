# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Playground threshold comparison (product v4)."""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402,F401

try:
    from backend.routers import playground as pg  # noqa: E402
except ImportError:
    from routers import playground as pg  # type: ignore[no-redef]  # noqa: E402


def test_threshold_flips_the_decision_for_a_normal_intent() -> None:
    out = pg.playground_compare(pg.CompareRequest(query="Quero ver o saldo da minha conta", thresholds=[0.1, 0.95]))
    decs = {c["threshold"]: c["decision"] for c in out["comparisons"]}
    assert decs[0.1] in ("PASSTHROUGH", "FLAG")  # released when the bar is low
    assert decs[0.95] in ("REASK", "ESCALATE")  # withheld when the bar is high
    assert out["n_distinct_decisions"] >= 2


def test_high_risk_intent_escalates_at_every_threshold() -> None:
    out = pg.playground_compare(
        pg.CompareRequest(query="nao aguento mais, quero acabar com tudo", thresholds=[0.1, 0.5, 0.95])
    )
    assert all(c["decision"] == "ESCALATE" for c in out["comparisons"])
    assert all(c["released"] is False for c in out["comparisons"])
