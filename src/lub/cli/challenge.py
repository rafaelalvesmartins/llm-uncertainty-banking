# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""``lub challenge-nightly`` -- scheduled continuous effective challenge.

Model validation in a bank is an annual, manual event. The point of this
command is to make it a nightly, automatic one: run it on a schedule against
the ledger a deployment writes to, and a calibration regression surfaces as a
red build the next morning rather than as a finding eleven months later.

It answers two questions and **fails closed** on either:

* Has the deployment's calibration drifted past the bounded context's target?
  (``lub.governance.drift.enforce_drift`` — the SR 11-7 ongoing-monitoring
  question.)
* Is the challenge layer itself well calibrated? (``MetaCalibrator`` — the
  monitoring layer scored against its own matured claims.)

The report is written whether the run passes or fails: evidence of a breach
is exactly the artefact a reviewer needs, so it must survive the failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import structlog
import typer

from lub.cli import EXIT_POLICY, EXIT_USER, app

if TYPE_CHECKING:
    from lub.challenge.nightly import ChallengeVerdict

__all__ = ["challenge_nightly"]

_LOG = structlog.get_logger("lub.cli.challenge")


def _render_report(verdict: ChallengeVerdict, *, ledger_path: Path) -> str:
    """Render the markdown evidence record for one nightly run."""
    measured = "n/a" if verdict.measured_ece is None else f"{verdict.measured_ece:.4f}"
    return "\n".join(
        [
            "# Continuous effective challenge — nightly run",
            "",
            f"- Status: **{verdict.status}**",
            f"- Generated at: {verdict.generated_at.isoformat()}",
            f"- Ledger: `{ledger_path}`",
            f"- Bounded context: `{verdict.context_name}`",
            "",
            "## Deployment calibration (bounded-context target)",
            "",
            f"- Measured ECE: {measured}",
            f"- Target ECE: {verdict.target_ece:.4f}",
            f"- Labelled answers: {verdict.n_samples} (minimum {verdict.min_samples})",
            "",
            f"```\n{verdict.reason}\n```",
            "",
            "## Challenge-layer meta-calibration",
            "",
            f"- Matured claims scored: {verdict.meta_observations}",
            f"- Pending claims (horizon not yet elapsed): {verdict.pending_claims}",
            f"- Meta ECE over matured claims: {verdict.meta_ece:.4f}",
            "",
            "A claim counts only once its revisit horizon has elapsed; pending",
            "claims are withheld rather than missing.",
            "",
        ]
    )


@app.command("challenge-nightly")
def challenge_nightly(
    ledger: Path = typer.Option(..., "--ledger", help="Path to an existing lub ledger database."),
    context: str = typer.Option(
        "regulatory-qa", "--context", help="Bounded context whose calibration target applies."
    ),
    report_out: Path = typer.Option(
        Path("challenge_nightly_report.md"), "--report-out", help="Where to write the report."
    ),
    method: str = typer.Option("confidence", "--method", help="Score method to evaluate."),
    min_samples: int = typer.Option(10, "--min-samples", help="Minimum labelled answers required."),
) -> None:
    """Run continuous effective challenge over a ledger; fail closed on breach."""
    from lub.challenge.nightly import run_nightly_challenge
    from lub.governance.contexts import default_registry
    from lub.ledger import Ledger

    if not ledger.exists():
        _LOG.error("challenge_nightly.ledger_not_found", path=str(ledger))
        typer.echo(f"error: ledger not found: {ledger}", err=True)
        raise typer.Exit(code=EXIT_USER)

    try:
        ctx = default_registry().get(context)
    except KeyError as exc:
        _LOG.error("challenge_nightly.unknown_context", context=context)
        typer.echo(f"error: unknown bounded context: {context}", err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    with Ledger(ledger) as led:
        verdict = run_nightly_challenge(led, ctx, method=method, min_samples=min_samples)

    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(_render_report(verdict, ledger_path=ledger), encoding="utf-8")

    if not verdict.passed:
        _LOG.warning(
            "challenge_nightly.not_passed",
            status=verdict.status,
            context=ctx.name,
            report=str(report_out),
        )
        typer.echo(f"{verdict.status}: context {ctx.name!r}; see {report_out}", err=True)
        raise typer.Exit(code=EXIT_POLICY)

    _LOG.info(
        "challenge_nightly.pass",
        context=ctx.name,
        meta_ece=f"{verdict.meta_ece:.4f}",
        pending=verdict.pending_claims,
        report=str(report_out),
    )
    typer.echo(f"PASS: {ctx.name} within calibration target; report written to {report_out}")
