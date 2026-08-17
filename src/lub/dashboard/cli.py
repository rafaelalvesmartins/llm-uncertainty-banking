# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""lub.dashboard.cli -- offline dashboard generator.

Usage::

    lub-dashboard render --ledger ./uq_ledger.db --out /tmp/dashboard.html
    lub-dashboard render --ledger ./uq_ledger.db --format json --out -

Post pass-33 refactor: the ``--format`` argument is **registry-driven**
via :func:`lub.dashboard.protocols.list_renderers`, so any plug-in that
registers a new renderer (markdown, PDF, ...) becomes available here
automatically. The default formats ``html`` and ``json`` are auto-registered
when :mod:`lub.dashboard.render` is imported.

Spec: planning/29_Dashboard_Spec_2026-04-25.md section 5.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

__all__ = ["main", "build_parser"]


def _available_formats() -> list[str]:
    """Return registered renderer names; importing render auto-registers."""
    from lub.dashboard import render  # noqa: F401 -- import side-effect
    from lub.dashboard.protocols import list_renderers

    return list_renderers() or ["html", "json"]


def build_parser() -> argparse.ArgumentParser:
    """Build the ``lub-dashboard`` argparse surface."""
    parser = argparse.ArgumentParser(
        prog="lub-dashboard",
        description="Generate a self-contained dashboard from an LUB ledger.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    render = sub.add_parser("render", help="Render dashboard to file or stdout.")
    render.add_argument(
        "--ledger",
        required=True,
        type=Path,
        help="Path to the sqlite ledger (e.g. ./uq_ledger.db).",
    )
    render.add_argument(
        "--out",
        required=True,
        type=str,
        help="Output path; pass '-' to write to stdout.",
    )
    render.add_argument(
        "--format",
        choices=_available_formats(),
        default="html",
        help="Output format (default: html). Any registered renderer.",
    )
    render.add_argument(
        "--days",
        type=int,
        default=30,
        help="Window: report on the last N days (default: 30).",
    )
    render.add_argument(
        "--tenant",
        type=str,
        default="default",
        help="Tenant identifier (pass-through).",
    )
    render.add_argument(
        "--git-sha",
        type=str,
        default="unknown",
        help="Git SHA of the producing build (pass-through).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command != "render":
        parser.print_help(sys.stderr)
        return 2

    if not args.ledger.exists():
        print(f"error: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    # Lazy imports so `lub-dashboard --help` works without pulling the
    # whole lub package into memory.
    # Importing render is required to populate the renderer registry.
    from lub.dashboard import render  # noqa: F401
    from lub.dashboard.ledger_source import LedgerSnapshotSource
    from lub.dashboard.protocols import get_renderer
    from lub.dashboard.query import build_snapshot
    from lub.ledger import Ledger

    period_end = datetime.now(UTC)
    period_start = period_end - timedelta(days=args.days)

    ledger = Ledger(args.ledger)
    try:
        source = LedgerSnapshotSource(ledger)
        snapshot = build_snapshot(
            source=source,
            evidence_store=None,
            period_start=period_start,
            period_end=period_end,
            tenant=args.tenant,
            git_sha=args.git_sha,
        )
    finally:
        ledger.close()

    renderer = get_renderer(args.format)
    out = renderer(snapshot)

    if args.out == "-":
        sys.stdout.write(out)
        if not out.endswith("\n"):
            sys.stdout.write("\n")
    else:
        Path(args.out).write_text(out, encoding="utf-8")
        print(
            f"Wrote {args.format} dashboard to {args.out} "
            f"(window: {args.days} days, decisions: {snapshot.decisions_in_window}).",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
