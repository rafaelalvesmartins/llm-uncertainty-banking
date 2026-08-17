# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""End-to-end: `lub benchmark` → `lub drift` / `lub report` → `lub repro`.

Covers gap #6 from the integration audit: each CLI subcommand is
smoke-tested in isolation in ``test_cli.py``, but no test pipes them
together the way a real user does. This exercises the four-stage chain
that a banking reviewer runs to produce a reproducible AI RMF bundle:

1. ``lub benchmark`` — run on baseline, write result JSON.
2. ``lub benchmark`` — run with a different estimator, write a second
   result JSON so we have two distinct results for drift comparison.
3. ``lub drift`` — PSI + CBPE between the two result files.
4. ``lub report`` — render AI RMF markdown from the baseline result.
5. ``lub repro`` — re-run the baseline and verify hash match.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from lub.cli import app

runner = CliRunner(mix_stderr=False)


def _extract_json(text: str) -> dict:
    """Return the last top-level JSON object in *text*.

    Structlog may interleave info lines on stdout in some sandbox
    setups; this helper robustly locates the last balanced object.
    """
    stripped = text.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)
    depth = 0
    start = -1
    last: str | None = None
    for i, ch in enumerate(stripped):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                last = stripped[start : i + 1]
    if last is None:
        raise AssertionError(f"no JSON object found:\n{text}")
    return json.loads(last)


def _run_benchmark(out_dir: Path, estimator: str = "token_logprob") -> Path:
    result = runner.invoke(
        app,
        [
            "benchmark",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", estimator,
            "--dataset", "br_regulatory",
            "--limit", "4",
            "--seed", "0",
            "--out", str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.stdout + "\n---\n" + (result.stderr or "")
    files = sorted(out_dir.glob("*.json"))
    assert len(files) == 1
    return files[0]


def test_full_cli_chain_benchmark_drift_report_repro(tmp_path: Path) -> None:
    # Stage 1: baseline benchmark -----------------------------------
    baseline_dir = tmp_path / "baseline"
    baseline_file = _run_benchmark(baseline_dir, estimator="token_logprob")

    # Stage 2: second benchmark (different estimator → different
    # confidence distribution → non-trivial drift signal) -----------
    current_dir = tmp_path / "current"
    current_file = _run_benchmark(current_dir, estimator="self_consistency")

    # Stage 3: drift fails closed -- result files persist only aggregate
    # metrics, so the CLI refuses to fabricate a PSI verdict from them
    # (per-example drift lives in lub.calibration.drift / governance.drift).
    drift_result = runner.invoke(
        app,
        [
            "drift",
            "--reference", str(baseline_file),
            "--current", str(current_file),
        ],
    )
    assert drift_result.exit_code == 1, drift_result.stdout + "\n---\n" + (drift_result.stderr or "")
    assert "aggregate" in drift_result.stdout + (drift_result.stderr or "")

    # Stage 4: AI RMF report ---------------------------------------
    report_md = tmp_path / "airmf.md"
    report_result = runner.invoke(
        app,
        [
            "report",
            "--input", str(baseline_file),
            "--format", "md",
            "--out", str(report_md),
            "--report-type", "airmf",
        ],
    )
    assert report_result.exit_code == 0, report_result.stdout + "\n---\n" + (report_result.stderr or "")
    assert report_md.exists()
    md = report_md.read_text(encoding="utf-8")
    for section in ("## Govern", "## Map", "## Measure", "## Manage"):
        assert section in md

    # Stage 5: repro — same inputs, same hash ----------------------
    repro_result = runner.invoke(app, ["repro", str(baseline_file)])
    assert repro_result.exit_code == 0, repro_result.stdout + "\n---\n" + (repro_result.stderr or "")
    repro_payload = _extract_json(repro_result.stdout)
    assert repro_payload["hash_match"] is True
    assert repro_payload["diffs"] == {}


def test_cli_chain_oscal_report_from_result(tmp_path: Path) -> None:
    """Separate, shorter chain: benchmark → OSCAL JSON report. Covers
    the alternate report-type branch that the AI RMF test does not hit.
    """
    out_dir = tmp_path / "results"
    result_file = _run_benchmark(out_dir)

    oscal_out = tmp_path / "oscal.json"
    oscal = runner.invoke(
        app,
        [
            "report",
            "--input", str(result_file),
            "--format", "json",
            "--out", str(oscal_out),
            "--report-type", "oscal",
        ],
    )
    assert oscal.exit_code == 0, oscal.stdout + "\n---\n" + (oscal.stderr or "")
    assert oscal_out.exists()
    raw = oscal_out.read_text(encoding="utf-8")
    # At least one OSCAL component-definition envelope must parse.
    found = False
    for chunk in [c for c in raw.split("\n\n") if c.strip()]:
        try:
            payload = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if "component-definition" in payload:
            found = True
            break
    assert found, f"no component-definition envelope in OSCAL output:\n{raw[:500]}"
