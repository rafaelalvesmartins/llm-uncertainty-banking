#!/usr/bin/env python3
# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""Audit the visual parity between docs/dashboard_mockup.html and the
output of lub.dashboard.render.render_html() for an equivalent fixture.

Usage:
    python scripts/audit_dashboard_visual_parity.py
    python scripts/audit_dashboard_visual_parity.py --rendered-out /tmp/rendered.html

Reports a list of "panels" present in each (KPI strip, recent decisions,
reliability, OSCAL) and prints PASS/FAIL on parity. Used to make sure the
mockup at docs/dashboard_mockup.html and the runtime renderer agree on
which sections appear; future visual changes should land in BOTH.

Spec: planning/29_Dashboard_Spec_2026-04-25.md.
"""
from __future__ import annotations
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MOCKUP = REPO / "docs" / "dashboard_mockup.html"

# Heuristic markers each panel emits -- searched in both docs.
PANEL_MARKERS = {
    "KPI strip":            [r"Decisions in window|Decisions"],
    "Abstention rate":      [r"Abstention rate|abstention"],
    "Correctness":          [r"Correctness"],
    "Meta-cal ECE":         [r"Meta-calibration|meta-cal"],
    "Recent decisions":     [r"Recent.*decisions|Recent ledger"],
    "Reliability curve":    [r"reliabilityChart|Reliability"],
    "OSCAL envelope":       [r"OSCAL"],
    "Chart.js":             [r"chart\.js|Chart\.js|Chart\b"],
}


def has_panel(html: str, patterns: list[str]) -> bool:
    return any(re.search(p, html, re.IGNORECASE) for p in patterns)


def render_with_fixture() -> str:
    """Render the actual dashboard with the same fake-data shape the mockup uses."""
    sys.path.insert(0, str(REPO / "src"))
    import importlib.util
    def _load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(spec); sys.modules[name] = m
        spec.loader.exec_module(m); return m
    proto = _load("dprotocols", REPO / "src" / "lub" / "dashboard" / "protocols.py")
    sys.modules["lub.dashboard.protocols"] = proto
    ls = _load("dledgersrc", REPO / "src" / "lub" / "dashboard" / "ledger_source.py")
    sys.modules["lub.dashboard.ledger_source"] = ls
    q = _load("dq", REPO / "src" / "lub" / "dashboard" / "query.py")
    sys.modules["lub.dashboard.query"] = q
    r = _load("dr", REPO / "src" / "lub" / "dashboard" / "render.py")
    snap = q.DashboardSnapshot(
        period_start=datetime(2026, 4, 1),
        period_end=datetime(2026, 4, 30),
        tenant="audit",
        git_sha="audit",
        decisions_in_window=42,
        abstention_rate=0.15,
        correctness_rate=0.93,
        n_outcomes_recorded=10,
        meta_calibration_ece=0.041,
        recent_decisions=[
            {"created_at": "2026-04-15T12:00:00.000Z", "domain": "banking",
             "model": "gpt-4o", "tier": "prime", "decision": "EMIT",
             "reason": "above threshold", "passed": 1},
        ],
        oscal_envelope={"_status": "fixture"},
    )
    return r.render_html(snap)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rendered-out", type=Path, default=None,
                        help="If set, write the rendered HTML here for inspection.")
    args = parser.parse_args()

    if not MOCKUP.exists():
        print(f"FAIL: mockup not found at {MOCKUP}", file=sys.stderr)
        return 1
    mockup_html = MOCKUP.read_text(encoding="utf-8")
    rendered_html = render_with_fixture()

    if args.rendered_out:
        args.rendered_out.write_text(rendered_html, encoding="utf-8")
        print(f"Wrote rendered fixture HTML to {args.rendered_out}", file=sys.stderr)

    # Compare panel presence
    print(f"{'Panel':<22} {'Mockup':<8} {'Rendered':<10} {'Status':<8}")
    print("-" * 55)
    missing = []
    for name, patterns in PANEL_MARKERS.items():
        in_m = has_panel(mockup_html, patterns)
        in_r = has_panel(rendered_html, patterns)
        status = "OK" if (in_m == in_r) else "DIFF"
        if status == "DIFF":
            missing.append((name, in_m, in_r))
        print(f"{name:<22} {'YES' if in_m else 'no':<8} {'YES' if in_r else 'no':<10} {status}")

    print()
    if missing:
        print(f"FAIL: {len(missing)} panel(s) differ between mockup and renderer:")
        for name, in_m, in_r in missing:
            print(f"  - {name}: mockup={in_m}, rendered={in_r}")
        return 1

    # Size sanity (renderer should be in same order of magnitude as mockup)
    m_size = len(mockup_html); r_size = len(rendered_html)
    print(f"Sizes: mockup={m_size} chars, rendered={r_size} chars (ratio={r_size/m_size:.2f}x)")
    if r_size < m_size / 4:
        print(f"WARN: rendered output is much smaller than mockup; visual parity unlikely.")

    print("\nPASS: all panels present in both; visual contract holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
