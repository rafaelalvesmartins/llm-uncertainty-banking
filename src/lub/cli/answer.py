# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""``lub answer`` — score a single prompt and print the result as JSON."""

from __future__ import annotations

import json

import structlog
import typer

from lub.cli import EXIT_INTERNAL, EXIT_USER, app
from lub.pipeline import UncertaintyPipeline

__all__ = ["answer", "version"]

_LOG = structlog.get_logger("lub.cli.answer")


@app.command()
def answer(
    prompt: str = typer.Argument(..., help="The question to ask the model."),
    model: str = typer.Option(..., "--model", "-m", help="Model id (backend-specific)."),
    backend: str = typer.Option("hf", "--backend", "-b", help="hf|openai|anthropic|vllm|dummy"),
    estimator: str = typer.Option(
        "semantic_entropy",
        "--estimator",
        "-e",
        help="token_logprob|self_consistency|semantic_entropy|conformal",
    ),
    refusal_threshold: float = typer.Option(
        0.5,
        "--refusal-threshold",
        min=0.0,
        max=1.0,
        help="Confidence below this refuses the answer (0.0–1.0).",
    ),
) -> None:
    """Score a single prompt and print ``UncertaintyResult`` as JSON."""
    try:
        pipe = UncertaintyPipeline.from_pretrained(
            model=model,
            backend=backend,
            estimator=estimator,
            refusal_threshold=refusal_threshold,
        )
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=EXIT_USER) from exc
    except (ImportError, RuntimeError, TypeError) as exc:
        _LOG.error("answer.build_failed", error=str(exc))
        raise typer.Exit(code=EXIT_INTERNAL) from exc

    try:
        result = pipe.answer(prompt)
    except (RuntimeError, ValueError, OSError) as exc:
        _LOG.error("answer.run_failed", error=str(exc))
        raise typer.Exit(code=EXIT_INTERNAL) from exc

    payload = {
        "answer": result.answer,
        "confidence": result.confidence,
        "should_refuse": result.should_refuse,
        "raw_scores": result.raw_scores,
    }
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@app.command()
def version() -> None:
    """Print the installed package version."""
    from importlib import metadata as importlib_metadata

    try:
        v = importlib_metadata.version("llm-uncertainty-banking")
    except importlib_metadata.PackageNotFoundError:
        v = "0.0.0+local"
    typer.echo(v)
