# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""``lub report`` — render AI RMF / OSCAL / Giskard reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, cast

import structlog
import typer

from lub.cli import EXIT_INTERNAL, EXIT_USER, app

__all__ = ["report"]

_LOG = structlog.get_logger("lub.cli.report")


@app.command()
def report(
    input: Path = typer.Option(..., "--input", "-i", help="Result file or directory."),
    format: str = typer.Option(
        "md", "--format", "-f", help="md|html (for AIRMF) or json (for OSCAL)"
    ),
    out: Path | None = typer.Option(None, "--out", "-o", help="Output file path"),
    report_type: str = typer.Option("airmf", "--report-type", "-t", help="airmf|oscal|giskard"),
) -> None:
    """Render an AI RMF or OSCAL report from one or more benchmark result files."""
    from lub.reports.factory import create_reporter
    from lub.types import BenchmarkResult

    if not input.exists():
        _LOG.error("report.input_not_found", path=str(input))
        typer.echo(f"error: input path does not exist: {input}", err=True)
        raise typer.Exit(code=EXIT_USER)

    if report_type not in ("airmf", "oscal", "giskard"):
        _LOG.error("report.bad_report_type", report_type=report_type)
        typer.echo(
            f"error: report-type must be 'airmf', 'oscal', or 'giskard', got {report_type!r}",
            err=True,
        )
        raise typer.Exit(code=EXIT_USER)

    if report_type == "airmf" and format not in ("md", "html"):
        _LOG.error("report.bad_format", report_type=report_type, format=format)
        typer.echo(f"error: for AIRMF, format must be 'md' or 'html', got {format!r}", err=True)
        raise typer.Exit(code=EXIT_USER)
    if report_type == "oscal" and format != "json":
        _LOG.error("report.bad_format", report_type=report_type, format=format)
        typer.echo(f"error: for OSCAL, format must be 'json', got {format!r}", err=True)
        raise typer.Exit(code=EXIT_USER)
    if report_type == "giskard" and format not in ("json", "md"):
        _LOG.error("report.bad_format", report_type=report_type, format=format)
        typer.echo(f"error: for Giskard, format must be 'json' or 'md', got {format!r}", err=True)
        raise typer.Exit(code=EXIT_USER)

    if out is None:
        if report_type == "airmf":
            out = Path("airmf_report.md" if format == "md" else "airmf_report.html")
        elif report_type == "giskard":
            out = Path("giskard_report.json" if format == "json" else "giskard_report.md")
        else:
            out = Path("oscal_report.json")

    files = sorted(input.glob("*.json")) if input.is_dir() else [input]
    if not files:
        _LOG.error("report.no_results", path=str(input))
        typer.echo(f"error: no JSON result files found in {input}", err=True)
        raise typer.Exit(code=EXIT_USER)

    try:
        results = [
            BenchmarkResult.model_validate_json(p.read_text(encoding="utf-8")) for p in files
        ]
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        _LOG.error("report.parse_failed", error=str(exc), n_files=len(files))
        typer.echo(f"error: failed to parse result files: {exc}", err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    try:
        reporter = create_reporter(
            results=results,
            report_type=cast(Literal["airmf", "oscal", "giskard"], report_type),
        )
        saved = reporter.save(out, format=cast(Literal["md", "html", "json"], format))
    except (ValueError, RuntimeError, OSError) as exc:
        _LOG.error("report.failed", error=str(exc))
        raise typer.Exit(code=EXIT_INTERNAL) from exc

    _LOG.info("report.written", path=str(saved), n_results=len(results), report_type=report_type)
