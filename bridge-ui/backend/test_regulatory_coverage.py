# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Regulatory coverage endpoint — multi-framework crosswalk from lub.

Asserts /compliance/frameworks surfaces the full lub compliance suite with real
controls across jurisdictions, so the dashboard can show multi-framework
governance (not a single regime).

Run from the project root::

    pytest bridge-ui/backend/test_regulatory_coverage.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402,F401  (ensures the same module/env as the app)

try:
    from backend.routers import compliance as comp  # noqa: E402
except ImportError:
    from routers import compliance as comp  # type: ignore[no-redef]  # noqa: E402


def test_frameworks_cover_multiple_jurisdictions() -> None:
    p = comp.compliance_frameworks()
    assert p["n_frameworks"] >= 5
    assert p["n_jurisdictions"] >= 3
    assert p["n_controls_total"] >= 20
    keys = {f["key"] for f in p["frameworks"]}
    # Brazil + EU + US/Fed are the headline jurisdictions for a bank buyer.
    assert {"BCB", "EU_AI_ACT", "SR_11_7"}.issubset(keys)


def test_each_framework_has_real_controls() -> None:
    p = comp.compliance_frameworks()
    for fw in p["frameworks"]:
        assert fw["title"]
        assert fw["jurisdiction"]
        assert fw["n_controls"] == len(fw["controls"])
        for c in fw["controls"]:
            assert c["control_id"]
            assert c["control_title"]
            assert c["description"]
    # totals are internally consistent
    assert p["n_controls_total"] == sum(f["n_controls"] for f in p["frameworks"])
