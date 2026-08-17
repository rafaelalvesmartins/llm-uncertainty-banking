#!/usr/bin/env python3
"""Measure the canonical numbers straight from the code — the single source of truth.

The petition/README/CHANGELOG numbers (source files, tests, estimators, regimes)
have historically been hand-copied and drifted from reality (see
planning/CANONICAL_FACTS.md and planning/35). This script computes them from the
tree so a doc-writer or the counsel meeting can reconcile against a real count
instead of trusting prose.

Run from anywhere inside the repo (paths resolve relative to this file):

    python scripts/measure_metrics.py            # fast counts
    python scripts/measure_metrics.py --collect  # + pytest --co (slower)

It never writes anything. Exit code is always 0 (it is a report, not a gate) —
wire it as a drift gate only after counsel ratifies the canonical values.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent  # llm-uncertainty-banking/
SRC = REPO / "src" / "lub"
TESTS = REPO / "tests"
CROSSWALK = SRC / "reports" / "crosswalk_data.toml"


def _count_py(root: Path, *, exclude_init: bool) -> int:
    files = [p for p in root.rglob("*.py") if not (exclude_init and p.name == "__init__.py")]
    return len(files)


def _count_test_defs(root: Path) -> int:
    total = 0
    for p in root.rglob("*.py"):
        total += sum(1 for line in p.read_text(encoding="utf-8").splitlines() if "def test_" in line)
    return total


def _estimators() -> tuple[int, int, list[str]]:
    """(listed, resolvable, phantom-keys) from the runtime registry."""
    from lub.uncertainty.base import get_estimator_cls, list_estimators

    keys = list(list_estimators())
    phantom = []
    for k in keys:
        try:
            get_estimator_cls(k)
        except Exception:
            phantom.append(k)
    return len(keys), len(keys) - len(phantom), phantom


def _families() -> tuple[int, int]:
    from lub.uncertainty.families import FAMILIES

    return len(FAMILIES), sum(len(v) for v in FAMILIES.values())


def _crosswalk() -> tuple[int, int, int]:
    with CROSSWALK.open("rb") as fh:
        data = tomllib.load(fh)
    metrics = data.get("metrics", {})
    controls = data.get("controls", {})
    # Regimes are the per-metric column keys (NIST_GENAI, EU_AI_ACT, ...),
    # not a field on controls; trust_dimension is a label, not a regime.
    regimes: set[str] = set()
    if isinstance(metrics, dict):
        for row in metrics.values():
            if isinstance(row, dict):
                regimes.update(k for k in row if k != "trust_dimension")
    n_metrics = len(metrics) if isinstance(metrics, dict) else 0
    # controls includes the 5 SR-11-7 cross-reference controls; exclude them.
    n_controls = sum(
        1
        for k, v in (controls.items() if isinstance(controls, dict) else [])
        if isinstance(v, dict) and not str(k).upper().startswith("SR_11")
    )
    return len(regimes), n_metrics, n_controls


def _collect_count() -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(TESTS), "--co", "-q"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    for line in reversed(proc.stdout.splitlines()):
        if "test" in line and "collected" in line:
            return line.strip()
        if line.strip().endswith(("tests", "test")) and line.strip()[0].isdigit():
            return line.strip()
    return "(could not parse pytest --co output)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--collect", action="store_true", help="also run pytest --co (slower)")
    args = ap.parse_args()

    rows: list[tuple[str, str]] = []
    rows.append(("Source files (src/lub/**/*.py)", str(_count_py(SRC, exclude_init=False))))
    rows.append(("  ... excluding __init__.py", str(_count_py(SRC, exclude_init=True))))
    rows.append(("Static test defs (def test_ under tests/)", str(_count_test_defs(TESTS))))

    try:
        listed, resolvable, phantom = _estimators()
        note = "" if not phantom else f"  (phantom, unresolvable: {', '.join(phantom)})"
        rows.append(("Estimators listed", str(listed)))
        rows.append(("Estimators resolvable by name", f"{resolvable}{note}"))
    except Exception as exc:  # pragma: no cover - import guard
        rows.append(("Estimators", f"(import failed: {exc!r} — set PYTHONPATH to src/)"))

    try:
        fam, members = _families()
        rows.append(("Estimator families (FAMILIES)", f"{fam} families / {members} members"))
    except Exception as exc:  # pragma: no cover
        rows.append(("Estimator families", f"(import failed: {exc!r})"))

    try:
        regimes, metrics, controls = _crosswalk()
        rows.append(("Crosswalk regimes / metrics / controls", f"{regimes} / {metrics} / {controls}"))
    except Exception as exc:  # pragma: no cover
        rows.append(("Crosswalk", f"(parse failed: {exc!r})"))

    if args.collect:
        rows.append(("pytest --co (collected)", _collect_count()))

    width = max(len(label) for label, _ in rows)
    print(f"\nCanonical metrics — measured from {REPO.name} at HEAD\n")
    for label, value in rows:
        print(f"  {label.ljust(width)}   {value}")
    print(
        "\nCoverage: run  python -m pytest tests -q --cov=lub --cov-report=term  "
        "(the config omits 8 modules incl. monte_carlo_dropout.py).\n"
        "Reconcile these against planning/CANONICAL_FACTS.md before citing in the petition.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
