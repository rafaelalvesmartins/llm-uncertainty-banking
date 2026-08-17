# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Command-line interface for ``lub``.

Exposes ten subcommands via Typer, split into focused modules:

* :mod:`lub.cli.answer`    — ``lub answer`` (score a single prompt) +
  ``lub version`` (print the installed package version)
* :mod:`lub.cli.benchmark` — ``lub benchmark`` (run a dataset end-to-end)
* :mod:`lub.cli.report`    — ``lub report`` (AI RMF / OSCAL / Giskard reports)
* :mod:`lub.cli.inspect`   — ``lub list``, ``lub scan``, ``lub drift``,
  ``lub repro`` (inspection + reproducibility utilities)
* :mod:`lub.cli.run_swarm` — ``lub run-swarm`` (materialize a calibrated
  agent pack from a dotted-path factory and dry-run / emit a ruflo
  JSON-RPC handshake / drive it locally; ADR-002, shipped 2026-04-26)
* :mod:`lub.cli.challenge` — ``lub challenge-nightly`` (scheduled continuous
  effective challenge over a ledger; fails closed on a calibration breach)

The canonical 5-subcommand surface cited in the public README and
``planning/CANONICAL_FACTS.md`` is ``answer | benchmark | report |
repro | version``; ``list``, ``scan``, ``drift`` ship under the
"integrations" heading in the same docs; ``run-swarm`` ships under the
"orchestration" heading and is the user-facing entry point recommended
by ADR-002.

Exit codes: ``0`` success, ``1`` user error, ``2`` internal error,
``3`` governance-policy breach.
"""

from __future__ import annotations

import logging
import sys

import structlog
import typer

app = typer.Typer(
    name="lub",
    help="llm-uncertainty-banking CLI",
    no_args_is_help=True,
    add_completion=False,
)

EXIT_OK = 0
EXIT_USER = 1
EXIT_INTERNAL = 2
EXIT_POLICY = 3
"""A governance policy was breached — the command ran fine, the model did not.

Distinct from EXIT_INTERNAL so a scheduled job can tell "the check failed"
(act on the model) from "the checker failed" (act on the pipeline).
"""

_LOG = structlog.get_logger("lub.cli")


def configure_logging(verbose: bool, quiet: bool) -> None:
    """Set up structlog with the requested verbosity."""
    if verbose and quiet:
        raise typer.BadParameter("--quiet and --verbose are mutually exclusive")
    level = logging.WARNING if quiet else logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, stream=sys.stderr, format="%(message)s")
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


@app.callback()
def _main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Silence info logging."),
) -> None:
    """llm-uncertainty-banking command-line entry point."""
    try:
        configure_logging(verbose=verbose, quiet=quiet)
    except typer.BadParameter as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=EXIT_USER) from exc


# Register subcommands by importing each module (side effect: decorators
# register commands on ``app``).
import lub.cli.answer as _answer  # noqa: E402, F401
import lub.cli.benchmark as _benchmark  # noqa: E402, F401
import lub.cli.challenge as _challenge  # noqa: E402, F401
import lub.cli.inspect as _inspect  # noqa: E402, F401
import lub.cli.report as _report  # noqa: E402, F401
import lub.cli.run_swarm as _run_swarm  # noqa: E402, F401

__all__ = ["app"]
