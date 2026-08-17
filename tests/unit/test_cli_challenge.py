# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Unit tests for :mod:`lub.cli.challenge` (``lub challenge-nightly``).

The command is the scheduled entry point for continuous effective challenge:
it evaluates calibration drift against a bounded context and the CEC layer's
own meta-calibration over a ledger, writes a report, and **fails closed** —
a breach must leave a non-zero exit code so a nightly job goes red instead of
printing a warning nobody reads.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lub.cli import EXIT_POLICY, EXIT_USER, app
from lub.ledger import Ledger

runner = CliRunner(mix_stderr=False)


def _seed(path: Path, *, n: int, confidence: float, correct: bool) -> None:
    """Write ``n`` answers at a fixed confidence and correctness."""
    with Ledger(path) as led:
        for i in range(n):
            qid = led.log_query(prompt=f"q-{i}", domain="regulatory")
            aid = led.log_answer(
                query_id=qid,
                model="dummy",
                backend="dummy",
                answer=f"a-{i}",
                cost=0.0,
            )
            led.log_score(answer_id=aid, method="confidence", value=confidence)
            led.update_outcome(answer_id=aid, correct=correct, ground_truth=f"a-{i}")


@pytest.fixture()
def calibrated_ledger(tmp_path: Path) -> Iterator[Path]:
    """Confident and correct — measured ECE near zero, well inside target."""
    p = tmp_path / "calibrated.sqlite"
    _seed(p, n=40, confidence=0.98, correct=True)
    yield p


@pytest.fixture()
def drifted_ledger(tmp_path: Path) -> Iterator[Path]:
    """Confident and wrong — the calibration breach a nightly run must catch."""
    p = tmp_path / "drifted.sqlite"
    _seed(p, n=40, confidence=0.99, correct=False)
    yield p


# --- the happy path ---------------------------------------------------------


def test_calibrated_ledger_exits_zero_and_writes_a_report(
    calibrated_ledger: Path, tmp_path: Path
) -> None:
    report = tmp_path / "report.md"

    result = runner.invoke(
        app,
        ["challenge-nightly", "--ledger", str(calibrated_ledger), "--report-out", str(report)],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert report.exists()
    assert "ECE" in report.read_text(encoding="utf-8")


def test_report_names_the_context_and_the_sample_count(
    calibrated_ledger: Path, tmp_path: Path
) -> None:
    report = tmp_path / "report.md"

    runner.invoke(
        app,
        ["challenge-nightly", "--ledger", str(calibrated_ledger), "--report-out", str(report)],
    )
    body = report.read_text(encoding="utf-8")

    assert "regulatory-qa" in body
    assert "40" in body


# --- fail closed ------------------------------------------------------------


def test_calibration_breach_fails_the_run(drifted_ledger: Path, tmp_path: Path) -> None:
    """A drifted ledger must go red — this is the whole point of the job."""
    report = tmp_path / "report.md"

    result = runner.invoke(
        app,
        ["challenge-nightly", "--ledger", str(drifted_ledger), "--report-out", str(report)],
    )

    # Asserting the specific policy code, not merely "non-zero": an unknown
    # command also exits non-zero, which would let this pass vacuously.
    assert result.exit_code == EXIT_POLICY


def test_the_report_is_written_even_when_the_run_fails(
    drifted_ledger: Path, tmp_path: Path
) -> None:
    """Evidence of the breach must survive the failure, not be lost with it."""
    report = tmp_path / "report.md"

    runner.invoke(
        app,
        ["challenge-nightly", "--ledger", str(drifted_ledger), "--report-out", str(report)],
    )

    assert report.exists()
    assert "FAIL" in report.read_text(encoding="utf-8").upper()


# --- insufficient evidence is not a PASS ------------------------------------


def test_empty_ledger_is_inconclusive_and_fails_closed(tmp_path: Path) -> None:
    """Zero evidence must not read as 'validated'.

    ``check_drift`` deliberately reports a cold ledger as inconclusive with
    ``passed=True`` so a fresh deploy is not blocked — reasonable for the
    deploy path, wrong for a nightly governance verdict, where an empty or
    mispointed ledger would otherwise stay green forever.
    """
    p = tmp_path / "empty.sqlite"
    Ledger(p).close()
    report = tmp_path / "report.md"

    result = runner.invoke(
        app,
        ["challenge-nightly", "--ledger", str(p), "--report-out", str(report)],
    )

    assert result.exit_code == EXIT_POLICY
    assert "INCONCLUSIVE" in report.read_text(encoding="utf-8")


def test_below_min_samples_is_inconclusive(tmp_path: Path) -> None:
    p = tmp_path / "thin.sqlite"
    _seed(p, n=3, confidence=0.98, correct=True)  # calibrated, but only 3 rows
    report = tmp_path / "report.md"

    result = runner.invoke(
        app,
        ["challenge-nightly", "--ledger", str(p), "--report-out", str(report)],
    )

    assert result.exit_code == EXIT_POLICY
    assert "INCONCLUSIVE" in report.read_text(encoding="utf-8")


def test_operator_can_lower_the_evidence_bar_explicitly(tmp_path: Path) -> None:
    """--min-samples is the deliberate cold-start knob; lowering it must work."""
    p = tmp_path / "thin.sqlite"
    _seed(p, n=3, confidence=0.98, correct=True)

    result = runner.invoke(
        app,
        # --report-out is always given: the default is relative to the working
        # directory, so omitting it makes the test litter the repository.
        [
            "challenge-nightly",
            "--ledger",
            str(p),
            "--min-samples",
            "3",
            "--report-out",
            str(tmp_path / "report.md"),
        ],
    )

    assert result.exit_code == 0


# --- user errors ------------------------------------------------------------


def test_missing_ledger_is_a_user_error(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["challenge-nightly", "--ledger", str(tmp_path / "nope.sqlite")],
    )

    assert result.exit_code == EXIT_USER
    assert "not found" in (result.stdout + result.stderr).lower()


def test_unknown_context_is_a_user_error(calibrated_ledger: Path) -> None:
    result = runner.invoke(
        app,
        ["challenge-nightly", "--ledger", str(calibrated_ledger), "--context", "no-such-context"],
    )

    assert result.exit_code == EXIT_USER


# --- meta-calibration surface ----------------------------------------------


def test_report_surfaces_pending_cec_claims(calibrated_ledger: Path, tmp_path: Path) -> None:
    """Immature claims are held back from the curve; the report must say so."""
    from lub.challenge import MetaCalibrator

    with Ledger(calibrated_ledger) as led:
        mc = MetaCalibrator(ledger=led)
        mc.add_prediction("claim-young", 0.8, horizon_days=90)
        mc.record_outcome("claim-young", held_up=True)

    report = tmp_path / "report.md"
    runner.invoke(
        app,
        ["challenge-nightly", "--ledger", str(calibrated_ledger), "--report-out", str(report)],
    )
    body = report.read_text(encoding="utf-8")

    assert "pending" in body.lower()
    assert "1" in body
