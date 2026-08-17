# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Agent fleet / model inventory endpoint.

Asserts /fleet returns the portfolio: this live deployment (real ECE) plus seeded
sibling agents, with consistent summary counts.

Run from the project root::

    pytest bridge-ui/backend/test_fleet.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402,F401

try:
    from backend.routers import fleet as flt  # noqa: E402
except ImportError:
    from routers import fleet as flt  # type: ignore[no-redef]  # noqa: E402


def test_fleet_has_one_live_entry_and_seeded_siblings() -> None:
    p = flt.fleet()
    assert p["n_agents"] >= 5
    live = [a for a in p["agents"] if a.get("live")]
    assert len(live) == 1 and p["n_live"] == 1
    assert live[0]["name"] == "Bridge Banking AI"
    # the live entry's ECE matches the calibration source (or is None if lub absent)
    cal = server._load_live_calibration_metrics()
    assert live[0]["ece"] == cal.get("ece", {}).get("value")


def test_fleet_summary_is_consistent() -> None:
    p = flt.fleet()
    agents = p["agents"]
    assert p["n_production"] == sum(1 for a in agents if a["lifecycle"] == "produção")
    assert p["n_high_risk"] == sum(1 for a in agents if a["risk_tier"] == "alto")
    assert abs(p["cost_month_total_brl"] - sum(a.get("cost_month_brl") or 0 for a in agents)) < 0.01
    for a in agents:
        assert a["name"] and a["owner"] and a["risk_tier"] in {"alto", "médio", "baixo"}
        assert a["lifecycle"]
        assert isinstance(a["frameworks"], list)
