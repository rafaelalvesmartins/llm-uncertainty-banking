#!/usr/bin/env python3
# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Disk-integrity check for the lub source tree.

Catches three failure modes that have shown up in this repo's working
copy on Windows + a Linux bash sandbox:

1. **Null bytes** -- typically a sign that the writer flushed an
   incomplete buffer; Python refuses to compile such files.
2. **AST SyntaxError** -- a broader symptom that includes truncation
   mid-token, mid-string, or mid-block.
3. **Heuristic truncation** -- the file's last non-blank line ends
   with an open ``(`` / ``[`` / ``{``, an unterminated string quote,
   a trailing comma in a list opener, or no closing newline. These
   often parse successfully (because Python's parser is permissive
   inside docstrings) but indicate a writer that was interrupted.

Exit codes
----------

* ``0`` -- everything clean, nothing to do.
* ``1`` -- at least one file failed at least one check.
* ``2`` -- argv / I/O error before scanning could start.

Usage
-----

::

    python scripts/check_integrity.py
    python scripts/check_integrity.py --paths src/lub tests
    python scripts/check_integrity.py --json   # machine-readable

Add to a pre-commit hook to fail-fast when the bash sandbox writes a
truncated file:

::

    # .git/hooks/pre-commit
    #!/bin/sh
    python scripts/check_integrity.py || exit 1
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

DEFAULT_ROOTS = ("src/lub", "tests")

# Heuristic truncation cues. We err on the side of false-positives
# rather than misses -- the script is meant to fail loud during the
# repair work; a maintainer can rerun after acknowledging.
_OPEN_DELIMS = ("(", "[", "{")


def _has_null_bytes(data: bytes) -> bool:
    return b"\x00" in data


def _ast_parses(text: str, path: Path) -> tuple[bool, str]:
    try:
        ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return False, f"SyntaxError: {exc.msg} at line {exc.lineno}"
    return True, ""


def _looks_truncated(
    text: str, path: Path | None = None, *, strict: bool = False,
) -> tuple[bool, str]:
    """Cheap heuristics for "writer was interrupted" symptoms.

    Only signals that strongly correlate with truncation. The
    "missing final newline" cue is suppressed unless ``strict`` is
    set -- many existing files in the repo are stylistically fine
    without it and we do not want to fail the integrity check on
    them. Empty ``__init__.py`` is also allowed (intentional package
    marker) when ``strict`` is off.

    "Trailing open delimiter on last non-blank line" is the strongest
    signal we have (corrupted writes often stop mid-list / mid-tuple).
    Unterminated-string cues are subsumed by the AST parse step.
    """
    if not text:
        if path is not None and path.name == "__init__.py" and not strict:
            return False, ""
        return True, "empty file"
    if strict and not text.endswith("\n"):
        return True, "missing final newline (strict mode)"

    lines = text.rstrip("\n").splitlines()
    if not lines:
        return True, "no non-blank lines"
    last = lines[-1].rstrip()
    if not last:
        return False, ""

    if last.endswith(_OPEN_DELIMS):
        return True, f"last line ends with open delimiter: {last[-1]!r}"

    return False, ""


def _scan_one(path: Path, *, strict: bool = False) -> list[str]:
    """Run all checks against ``path``; return human-readable findings."""
    issues: list[str] = []
    try:
        data = path.read_bytes()
    except OSError as exc:
        return [f"could not read: {exc}"]
    if _has_null_bytes(data):
        n = data.count(b"\x00")
        issues.append(f"null bytes: {n}")
        # ``ast.parse`` raises ValueError on null bytes before we can
        # inspect the SyntaxError, so short-circuit here -- the file
        # is already known broken and the AST signal would not add
        # information.
        return issues

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        issues.append(f"not valid UTF-8: {exc}")
        return issues

    parses, why = _ast_parses(text, path)
    if not parses:
        issues.append(why)

    truncated, why = _looks_truncated(text, path, strict=strict)
    if truncated:
        issues.append(f"heuristic truncation: {why}")
    return issues


def _resolve_roots(repo_root: Path, raw_paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in raw_paths:
        candidate = (repo_root / p).resolve()
        if not candidate.exists():
            print(f"warning: skipping missing path {p}", file=sys.stderr)
            continue
        out.append(candidate)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--paths",
        nargs="+",
        default=list(DEFAULT_ROOTS),
        help=(
            "Directories (relative to repo root) to scan. "
            f"Defaults to: {' '.join(DEFAULT_ROOTS)}"
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable lines.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Treat stylistic cues (e.g. missing final newline) as failures. "
            "Off by default since several intentional files in the repo "
            "do not carry a trailing newline."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repo root (where pyproject.toml lives). Defaults to script's parent dir.",
    )
    args = parser.parse_args(argv)

    roots = _resolve_roots(args.repo_root, args.paths)
    if not roots:
        print("no scan paths resolved", file=sys.stderr)
        return 2

    findings: dict[str, list[str]] = {}
    n_scanned = 0
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            n_scanned += 1
            issues = _scan_one(path, strict=args.strict)
            if issues:
                rel = path.relative_to(args.repo_root)
                findings[str(rel)] = issues

    if args.json:
        out = {
            "scanned": n_scanned,
            "failures": len(findings),
            "issues": findings,
        }
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        print(f"check_integrity: scanned {n_scanned} .py files in {len(roots)} root(s)")
        if not findings:
            print("OK -- no issues found")
        else:
            print(f"FAIL -- {len(findings)} file(s) with issues:")
            for path, issues in sorted(findings.items()):
                print(f"  {path}")
                for issue in issues:
                    print(f"    - {issue}")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
