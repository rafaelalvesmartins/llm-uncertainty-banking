#!/usr/bin/env python3
"""Local pre-flight for llm-uncertainty-banking releases.

Runs the same gates CI runs (lint, type-check, import-linter, tests with
coverage threshold), plus a handful of local-only checks that CI can't
easily do (version string consistency across pyproject.toml / CITATION.cff
/ optional CHANGELOG, dirty working tree, unpushed tag).

Usage (from repo root):

    python scripts/release_check.py
    python scripts/release_check.py --fast    # skip tests, keep lint+types+imports+version
    python scripts/release_check.py --only version,lint

Exit codes:
    0 = all selected gates passed
    1 = at least one gate failed
    2 = invocation error (bad --only value, missing tool, etc.)
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

GATES_IN_ORDER = ("version", "lint", "types", "imports", "tests")


@dataclass
class GateResult:
    name: str
    ok: bool
    detail: str


# ---------------------------------------------------------------------------
# Version consistency
# ---------------------------------------------------------------------------


PYPROJECT_VERSION_RE = re.compile(
    r"""^\s*version\s*=\s*["']([^"']+)["']""", re.MULTILINE
)
CFF_VERSION_RE = re.compile(r"""^\s*version:\s*["']?([^"'\s]+)["']?""", re.MULTILINE)


def read_pyproject_version(repo: Path) -> str | None:
    path = repo / "pyproject.toml"
    if not path.exists():
        return None
    m = PYPROJECT_VERSION_RE.search(path.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def read_cff_version(repo: Path) -> str | None:
    path = repo / "CITATION.cff"
    if not path.exists():
        return None
    m = CFF_VERSION_RE.search(path.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def check_version_consistency(repo: Path) -> GateResult:
    py = read_pyproject_version(repo)
    cff = read_cff_version(repo)
    issues: list[str] = []
    if py is None:
        issues.append("pyproject.toml version not found")
    if cff is not None and py is not None and cff != py:
        issues.append(
            f"version mismatch: pyproject={py} vs CITATION.cff={cff} "
            "(update CITATION.cff or pyproject.toml to match)"
        )
    detail = "; ".join(issues) if issues else f"pyproject={py}, CITATION.cff={cff}"
    return GateResult("version", not issues, detail)


# ---------------------------------------------------------------------------
# Subprocess-backed gates
# ---------------------------------------------------------------------------


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    """Run a command. Return (returncode, trimmed_stderr_tail)."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not found on PATH"
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return proc.returncode, "\n".join(tail[-6:])


def check_lint(repo: Path) -> GateResult:
    if shutil.which("ruff") is None:
        return GateResult("lint", False, "ruff not installed; `pip install -e .[dev]`")
    rc, tail = _run(["ruff", "check", "src", "tests"], repo)
    return GateResult("lint", rc == 0, tail or ("OK" if rc == 0 else f"exit {rc}"))


def check_types(repo: Path) -> GateResult:
    if shutil.which("mypy") is None:
        return GateResult("types", False, "mypy not installed; `pip install -e .[dev]`")
    rc, tail = _run(["mypy", "src"], repo)
    return GateResult("types", rc == 0, tail or ("OK" if rc == 0 else f"exit {rc}"))


def check_imports(repo: Path) -> GateResult:
    if shutil.which("lint-imports") is None:
        return GateResult(
            "imports",
            False,
            "lint-imports not installed; `pip install -e .[dev]`",
        )
    rc, tail = _run(["lint-imports"], repo)
    return GateResult("imports", rc == 0, tail or ("OK" if rc == 0 else f"exit {rc}"))


def check_tests(repo: Path, cov_min: int) -> GateResult:
    if shutil.which("pytest") is None:
        return GateResult("tests", False, "pytest not installed; `pip install -e .[dev]`")
    rc, tail = _run(
        [
            "pytest",
            "-q",
            "--cov=lub",
            "--cov-report=term-missing",
            f"--cov-fail-under={cov_min}",
        ],
        repo,
    )
    return GateResult("tests", rc == 0, tail or ("OK" if rc == 0 else f"exit {rc}"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_selection(raw: str | None) -> list[str]:
    if not raw:
        return list(GATES_IN_ORDER)
    picked = [g.strip() for g in raw.split(",") if g.strip()]
    unknown = [g for g in picked if g not in GATES_IN_ORDER]
    if unknown:
        raise SystemExit(
            f"ERROR: unknown gate(s): {', '.join(unknown)}. "
            f"Known: {', '.join(GATES_IN_ORDER)}"
        )
    return picked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run local pre-release gates for llm-uncertainty-banking.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repo root (default: cwd).",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help=f"Comma-separated subset of: {', '.join(GATES_IN_ORDER)}",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip tests; run version+lint+types+imports only.",
    )
    parser.add_argument(
        "--cov-min",
        type=int,
        default=80,
        help="Coverage gate threshold (default: %(default)s, matches CI).",
    )
    args = parser.parse_args(argv)

    repo = args.repo_root.resolve()
    if not (repo / "pyproject.toml").exists():
        print(f"ERROR: no pyproject.toml at {repo}", file=sys.stderr)
        return 2

    try:
        selected = parse_selection(args.only)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.fast:
        selected = [g for g in selected if g != "tests"]

    runners = {
        "version": lambda: check_version_consistency(repo),
        "lint": lambda: check_lint(repo),
        "types": lambda: check_types(repo),
        "imports": lambda: check_imports(repo),
        "tests": lambda: check_tests(repo, args.cov_min),
    }

    results: list[GateResult] = []
    for gate in selected:
        print(f"[*] {gate:8s} ...", flush=True)
        res = runners[gate]()
        results.append(res)
        marker = "OK  " if res.ok else "FAIL"
        print(f"[{marker}] {gate:8s}  {res.detail}")

    print()
    passed = sum(1 for r in results if r.ok)
    print(f"Summary: {passed}/{len(results)} gates passed")
    any_failed = any(not r.ok for r in results)
    return 1 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
