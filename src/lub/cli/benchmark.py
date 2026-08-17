# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""``lub benchmark`` — run a dataset end-to-end and persist results."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import structlog
import typer

from lub.benchmarks.base import Dataset
from lub.benchmarks.correctness import CorrectnessFn, exact_match, fuzzy_match
from lub.cli import EXIT_INTERNAL, EXIT_USER, app
from lub.pipeline import UncertaintyPipeline

__all__ = ["benchmark"]

_LOG = structlog.get_logger("lub.cli.benchmark")

_CONFIG_KEYS: frozenset[str] = frozenset(
    {"model", "backend", "estimator", "dataset", "limit", "seed", "out", "correctness"}
)

# Correctness scorers selectable from the CLI. ``BenchmarkRunner`` has always accepted a
# pluggable ``correctness_fn``, but the CLI never exposed it, so every CLI run silently scored
# with strict ``exact_match`` — which marks a factually-correct verbose answer WRONG, understating
# accuracy and corrupting every calibration metric derived from those labels.
# ``choice_match`` is deliberately absent: it is a FACTORY that needs the dataset's label set,
# and the Dataset API does not expose one. Inventing a dataset-label API here would be scope
# creep; the Python API remains the way to use it.
_CORRECTNESS_FNS: dict[str, CorrectnessFn] = {
    "exact_match": exact_match,
    "fuzzy_match": fuzzy_match,
}


def _load_benchmark_config(path: Path) -> dict[str, Any]:
    """Load a TOML benchmark config and validate its keys."""
    if not path.exists():
        raise typer.BadParameter(f"config file not found: {path}")
    with path.open("rb") as f:
        data = tomllib.load(f)
    unknown = set(data) - _CONFIG_KEYS
    if unknown:
        raise typer.BadParameter(
            f"unknown config keys: {sorted(unknown)}; allowed: {sorted(_CONFIG_KEYS)}"
        )
    return data


def _resolve_dataset(name: str) -> Dataset:
    """Resolve dataset by name using the auto-registration registry."""
    import lub.benchmarks  # noqa: F401

    try:
        cls = Dataset.get_dataset_cls(name)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    return cls()


@app.command()
def benchmark(
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Model identifier (HF repo id, Ollama tag, OpenAI model name).",
    ),
    backend: str | None = typer.Option(
        None,
        "--backend",
        "-b",
        help="Backend key from the registry (e.g. 'hf', 'openai', 'ollama').",
    ),
    estimator: str | None = typer.Option(
        None,
        "--estimator",
        "-e",
        help="Uncertainty estimator key (e.g. 'semantic_entropy', 'token_sar', 'sentence_sar').",
    ),
    dataset: str | None = typer.Option(
        None,
        "--dataset",
        "-d",
        help="Dataset key registered under lub.benchmarks.",
    ),
    correctness: str | None = typer.Option(
        None,
        "--correctness",
        help=(
            "How an answer is scored as correct: 'exact_match' (default, strict) or "
            "'fuzzy_match' (containment/numeric-tolerant — use it for verbose free-text "
            "answers, where exact_match understates accuracy). 'choice_match' needs the "
            "dataset's label set and is only available via the Python API."
        ),
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Maximum examples to evaluate; default: full dataset.",
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Directory where the BenchmarkResult JSON is written.",
    ),
    seed: int | None = typer.Option(
        None,
        "--seed",
        help="Random seed passed to the runner for reproducibility.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="TOML config file; CLI flags override its values.",
    ),
) -> None:
    """Run a benchmark and write the resulting ``BenchmarkResult`` as JSON."""
    from lub.benchmarks.runner import BenchmarkRunner

    try:
        cfg = _load_benchmark_config(config) if config else {}
    except typer.BadParameter as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    resolved_model = model or cfg.get("model")
    resolved_backend = backend or cfg.get("backend", "hf")
    resolved_estimator = estimator or cfg.get("estimator", "semantic_entropy")
    resolved_dataset = dataset or cfg.get("dataset")
    resolved_limit = limit if limit is not None else cfg.get("limit")
    resolved_seed = seed if seed is not None else cfg.get("seed", 0)
    resolved_out = out or Path(cfg.get("out", "benchmarks/results"))

    missing = [
        k
        for k, v in [
            ("model", resolved_model),
            ("dataset", resolved_dataset),
        ]
        if not v
    ]
    if missing:
        typer.echo(
            f"error: missing required args: {missing}; provide via flags or --config",
            err=True,
        )
        raise typer.Exit(code=EXIT_USER)

    assert isinstance(resolved_model, str)
    assert isinstance(resolved_dataset, str)

    resolved_correctness = correctness or cfg.get("correctness", "exact_match")
    if resolved_correctness not in _CORRECTNESS_FNS:
        typer.echo(
            f"error: unknown correctness scorer {resolved_correctness!r}; "
            f"choose from {sorted(_CORRECTNESS_FNS)}",
            err=True,
        )
        raise typer.Exit(code=EXIT_USER)
    correctness_fn = _CORRECTNESS_FNS[resolved_correctness]

    try:
        pipe = UncertaintyPipeline.from_pretrained(
            model=resolved_model, backend=resolved_backend, estimator=resolved_estimator
        )
        ds = _resolve_dataset(resolved_dataset)
    except (ValueError, typer.BadParameter) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    runner = BenchmarkRunner(
        pipeline=pipe, dataset=ds, results_dir=resolved_out, correctness_fn=correctness_fn
    )
    try:
        record = runner.run(limit=resolved_limit, seed=resolved_seed)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=EXIT_USER) from exc
    except (RuntimeError, OSError) as exc:
        _LOG.error("benchmark.failed", error=str(exc))
        raise typer.Exit(code=EXIT_INTERNAL) from exc

    typer.echo(json.dumps(record.model_dump(), indent=2, sort_keys=True, default=str))
