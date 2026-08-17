# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""``lub list``, ``lub scan``, ``lub drift``, ``lub repro`` -- inspection utilities."""

from __future__ import annotations

import json
from pathlib import Path

import structlog
import typer

from lub.cli import EXIT_INTERNAL, EXIT_USER, app

__all__ = ["drift", "list_components", "repro", "scan"]

_LOG = structlog.get_logger("lub.cli.inspect")


@app.command()
def repro(
    results_file: Path = typer.Argument(..., help="A previously written BenchmarkResult JSON."),
    tolerance: float = typer.Option(1e-6, "--tolerance"),
) -> None:
    """Re-run a benchmark under its recorded config and verify metric match."""
    from lub.benchmarks.runner import BenchmarkRunner, content_hash
    from lub.cli.benchmark import _resolve_dataset
    from lub.pipeline import UncertaintyPipeline
    from lub.types import BenchmarkResult
    from lub.wrappers.base import ModelBackend

    if not results_file.exists():
        _LOG.error("repro.file_not_found", path=str(results_file))
        typer.echo(f"error: file not found: {results_file}", err=True)
        raise typer.Exit(code=EXIT_USER)
    try:
        original = BenchmarkResult.model_validate_json(results_file.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _LOG.error("repro.parse_failed", error=str(exc), path=str(results_file))
        typer.echo(f"error: failed to parse result file: {exc}", err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    backend_name, sep, model_id = original.backend.partition(":")
    if not sep:
        model_id = original.backend
    backend_key = ModelBackend.resolve_class_name(backend_name)

    try:
        pipe = UncertaintyPipeline.from_pretrained(
            model=model_id, backend=backend_key, estimator=original.estimator
        )
        ds = _resolve_dataset(original.dataset)
    except (ValueError, typer.BadParameter) as exc:
        _LOG.error(
            "repro.build_failed", error=str(exc), backend=backend_key, estimator=original.estimator
        )
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    runner = BenchmarkRunner(pipeline=pipe, dataset=ds)
    try:
        replayed = runner.run(limit=original.n, seed=original.seed, write=False)
    except Exception as exc:  # noqa: BLE001
        _LOG.error("repro.failed", error=str(exc))
        raise typer.Exit(code=EXIT_INTERNAL) from exc

    diffs: dict[str, tuple[float, float]] = {}
    for field in ("accuracy", "ece", "refusal_auroc"):
        a = float(getattr(original, field))
        b = float(getattr(replayed, field))
        if abs(a - b) > tolerance:
            diffs[field] = (a, b)

    hash_match = content_hash(original) == content_hash(replayed)
    payload = {
        "hash_match": hash_match,
        "diffs": {k: {"original": v[0], "replayed": v[1]} for k, v in diffs.items()},
        "original_dataset_hash": original.dataset_hash,
        "replayed_dataset_hash": replayed.dataset_hash,
    }
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))

    if diffs or original.dataset_hash != replayed.dataset_hash:
        raise typer.Exit(code=EXIT_USER)


@app.command(name="list")
def list_components(
    component: str = typer.Argument(
        "all",
        help=(
            "Component type to list: estimators, backends, datasets, regimes, mcp-tools, or all."
        ),
    ),
) -> None:
    """List available estimators, backends, datasets, regimes, and MCP tools."""
    from lub.benchmarks.base import Dataset
    from lub.uncertainty.base import list_estimators
    from lub.wrappers.base import list_backends

    sections: dict[str, list[str]] = {}

    if component in ("all", "estimators"):
        sections["Estimators"] = list_estimators()
    if component in ("all", "backends"):
        sections["Backends"] = list_backends()
    if component in ("all", "datasets"):
        sections["Datasets"] = Dataset.list_datasets()
    if component in ("all", "regimes"):
        try:
            from lub.reports.crosswalk import regimes

            sections["Regulatory regimes"] = [str(r) for r in regimes()]
        except ImportError:  # pragma: no cover
            sections["Regulatory regimes"] = ["(crosswalk module not available)"]
    if component in ("all", "mcp-tools"):
        from lub.mcp.server import list_all_tools

        sections["MCP tools"] = [t.name for t in list_all_tools()]

    if not sections:
        raise typer.BadParameter(
            f"unknown component {component!r}; choose from: "
            "estimators, backends, datasets, regimes, mcp-tools, all"
        )

    for title, items in sections.items():
        typer.echo(f"\n{title} ({len(items)}):")
        for item in items:
            typer.echo(f"  - {item}")
    typer.echo()


@app.command()
def scan(
    input: Path = typer.Option(..., "--input", "-i", help="Result file or directory."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Output file path."),
    format: str = typer.Option("json", "--format", "-f", help="json or md."),
) -> None:
    """Run vulnerability scan on benchmark results (Giskard-style)."""
    from lub.reports.giskard_report import scan_benchmark_result
    from lub.types import BenchmarkResult

    if not input.exists():
        _LOG.error("scan.input_not_found", path=str(input))
        typer.echo(f"error: input path does not exist: {input}", err=True)
        raise typer.Exit(code=EXIT_USER)

    files = sorted(input.glob("*.json")) if input.is_dir() else [input]
    if not files:
        _LOG.error("scan.no_results", path=str(input))
        typer.echo(f"error: no JSON result files found in {input}", err=True)
        raise typer.Exit(code=EXIT_USER)

    try:
        results = [
            BenchmarkResult.model_validate_json(p.read_text(encoding="utf-8")) for p in files
        ]
    except Exception as exc:  # noqa: BLE001
        _LOG.error("scan.parse_failed", error=str(exc), n_files=len(files))
        typer.echo(f"error: failed to parse result files: {exc}", err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    reports = [scan_benchmark_result(r) for r in results]

    if format == "json":
        output = json.dumps([r.to_dict() for r in reports], indent=2)
    elif format == "md":
        lines = ["# Vulnerability Scan Results", ""]
        for i, rpt in enumerate(reports):
            lines.append(f"## Run {i + 1}: {rpt.backend} / {rpt.estimator}")
            lines.append(f"- Worst severity: **{rpt.worst_severity}**")
            lines.append(f"- Passed: {'Yes' if rpt.passed else '**No**'}")
            lines.append(f"- Issues: {len(rpt.issues)}")
            lines.append("")
        output = "\n".join(lines)
    else:
        _LOG.error("scan.bad_format", format=format)
        typer.echo(f"error: format must be 'json' or 'md', got {format!r}", err=True)
        raise typer.Exit(code=EXIT_USER)

    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(output, encoding="utf-8")
        _LOG.info("scan.written", path=str(out), n_results=len(reports))
    else:
        typer.echo(output)


@app.command()
def drift(
    reference: Path = typer.Option(..., "--reference", "-r", help="Reference result file."),
    current: Path = typer.Option(..., "--current", "-c", help="Current result file."),
) -> None:
    """Drift check between two result files (fails closed -- see error)."""
    from lub.types import BenchmarkResult

    for path, label in [(reference, "reference"), (current, "current")]:
        if not path.exists():
            _LOG.error("drift.file_not_found", path=str(path), role=label)
            typer.echo(f"error: {label} file not found: {path}", err=True)
            raise typer.Exit(code=EXIT_USER)

    try:
        BenchmarkResult.model_validate_json(reference.read_text(encoding="utf-8"))
        BenchmarkResult.model_validate_json(current.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _LOG.error(
            "drift.parse_failed",
            error=str(exc),
            reference=str(reference),
            current=str(current),
        )
        typer.echo(f"error: failed to parse result files: {exc}", err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    # BenchmarkResult persists aggregate metrics only -- PSI/CBPE computed
    # over a handful of aggregate values has no statistical meaning, so
    # this command refuses rather than print a fabricated drift verdict.
    _LOG.error("drift.aggregate_only", reference=str(reference), current=str(current))
    typer.echo(
        "error: benchmark result files persist aggregate metrics, not "
        "per-example confidences, so a PSI/CBPE drift verdict computed from "
        "them would be statistically meaningless. Use "
        "lub.calibration.drift.analyze_drift on per-example confidence "
        "arrays, or lub.governance.drift.enforce_drift over a ledger.",
        err=True,
    )
    raise typer.Exit(code=EXIT_USER)
