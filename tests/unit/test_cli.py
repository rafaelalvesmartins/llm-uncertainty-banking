# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""CLI smoke tests exercising every subcommand against DummyBackend.

These tests invoke the Typer app via ``CliRunner`` so every path through
`lub.cli` runs in-process — no subprocess, no network, no real model
weights. The goal is coverage, not end-to-end validation; deeper
validation lives in `test_end_to_end.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lub.cli import app

# mix_stderr=False separates structlog output (stderr) from the command's
# JSON payload (stdout) so tests can cleanly _extract_json(result.stdout).
runner = CliRunner(mix_stderr=False)


def _extract_json(text: str) -> dict:
    """Return the last JSON object found in ``text``.

    Typer `echo(json.dumps(...))` emits the payload cleanly, but structlog's
    default ``ConsoleRenderer`` may interleave info lines on stdout in CI
    environments where stderr is redirected. This helper locates the final
    top-level JSON object so tests are robust to both.
    """
    stripped = text.strip()
    if stripped.startswith("{"):
        # Fast path: stdout is exactly the JSON payload.
        return json.loads(stripped)
    # Slow path: scan for the last balanced top-level object.
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
        raise AssertionError(f"no JSON object found in output:\n{text}")
    return json.loads(last)


def test_version_prints_semver() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip()  # non-empty


def test_answer_emits_json_with_dummy_backend() -> None:
    result = runner.invoke(
        app,
        [
            "answer",
            "What is the Basel III CET1 ratio?",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", "token_logprob",
            "--refusal-threshold", "0.0",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = _extract_json(result.stdout)
    assert "answer" in payload
    assert "confidence" in payload
    assert 0.0 <= payload["confidence"] <= 1.0


def test_answer_rejects_unknown_estimator() -> None:
    result = runner.invoke(
        app,
        [
            "answer",
            "q",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", "not-a-real-estimator",
        ],
    )
    assert result.exit_code == 1
    assert "unknown estimator" in result.stderr.lower()


def test_answer_with_self_consistency_estimator() -> None:
    result = runner.invoke(
        app,
        [
            "answer",
            "q",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", "self_consistency",
        ],
    )
    assert result.exit_code == 0


def test_benchmark_runs_on_br_regulatory(tmp_path: Path) -> None:
    out_dir = tmp_path / "results"
    result = runner.invoke(
        app,
        [
            "benchmark",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", "token_logprob",
            "--dataset", "br_regulatory",
            "--limit", "5",
            "--out", str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.stdout
    record = _extract_json(result.stdout)
    assert record["n"] == 5
    assert record["dataset"] == "br_regulatory"
    assert list(out_dir.glob("*.json")), "runner should have written a result file"


def test_benchmark_rejects_unknown_dataset() -> None:
    result = runner.invoke(
        app,
        [
            "benchmark",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", "token_logprob",
            "--dataset", "not-a-real-dataset",
        ],
    )
    assert result.exit_code == 1


def test_report_round_trip_md_and_html(tmp_path: Path) -> None:
    # Produce a fresh result JSON via benchmark, then render a report from it.
    out_dir = tmp_path / "results"
    bench = runner.invoke(
        app,
        [
            "benchmark",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", "token_logprob",
            "--dataset", "br_regulatory",
            "--limit", "3",
            "--out", str(out_dir),
        ],
    )
    assert bench.exit_code == 0

    md_out = tmp_path / "report.md"
    md = runner.invoke(
        app,
        ["report", "--input", str(out_dir), "--format", "md", "--out", str(md_out)],
    )
    assert md.exit_code == 0, md.stdout
    assert md_out.exists()
    content = md_out.read_text(encoding="utf-8")
    for section in ("## Govern", "## Map", "## Measure", "## Manage"):
        assert section in content

    html_out = tmp_path / "report.html"
    html = runner.invoke(
        app,
        ["report", "--input", str(out_dir), "--format", "html", "--out", str(html_out)],
    )
    assert html.exit_code == 0
    assert html_out.exists()
    assert html_out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_report_rejects_bad_format(tmp_path: Path) -> None:
    p = tmp_path / "nope.json"
    p.write_text("{}", encoding="utf-8")
    result = runner.invoke(
        app, ["report", "--input", str(p), "--format", "pdf", "--out", "x.md"]
    )
    assert result.exit_code == 1


def test_report_giskard_round_trip(tmp_path: Path) -> None:
    out_dir = tmp_path / "results"
    bench = runner.invoke(
        app,
        [
            "benchmark",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", "token_logprob",
            "--dataset", "br_regulatory",
            "--limit", "3",
            "--out", str(out_dir),
        ],
    )
    assert bench.exit_code == 0

    json_out = tmp_path / "vuln.json"
    result = runner.invoke(
        app,
        [
            "report",
            "--input", str(out_dir),
            "--report-type", "giskard",
            "--format", "json",
            "--out", str(json_out),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert json_out.exists()
    import json

    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert len(payload) >= 1
    assert "issues" in payload[0]

    md_out = tmp_path / "vuln.md"
    md_result = runner.invoke(
        app,
        [
            "report",
            "--input", str(out_dir),
            "--report-type", "giskard",
            "--format", "md",
            "--out", str(md_out),
        ],
    )
    assert md_result.exit_code == 0
    assert "Vulnerability Report" in md_out.read_text(encoding="utf-8")


def test_report_missing_input_path(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "report",
            "--input", str(tmp_path / "does-not-exist.json"),
            "--format", "md",
            "--out", str(tmp_path / "out.md"),
        ],
    )
    assert result.exit_code == 1


def test_repro_round_trip(tmp_path: Path) -> None:
    out_dir = tmp_path / "results"
    bench = runner.invoke(
        app,
        [
            "benchmark",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", "token_logprob",
            "--dataset", "br_regulatory",
            "--limit", "4",
            "--out", str(out_dir),
        ],
    )
    assert bench.exit_code == 0

    files = sorted(out_dir.glob("*.json"))
    assert len(files) == 1

    repro_result = runner.invoke(app, ["repro", str(files[0])])
    # Repro should produce identical metrics since DummyBackend is deterministic
    # and both runs use seed=0 on the same dataset.
    assert repro_result.exit_code == 0, repro_result.stdout
    payload = _extract_json(repro_result.stdout)
    assert payload["hash_match"] is True
    assert payload["diffs"] == {}


def test_repro_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["repro", str(tmp_path / "ghost.json")])
    assert result.exit_code == 1


@pytest.mark.parametrize("estimator", ["perplexity", "p_true", "eigenscore"])
def test_answer_with_newly_ported_estimators(estimator: str) -> None:
    result = runner.invoke(
        app,
        [
            "answer",
            "q",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", estimator,
        ],
    )
    assert result.exit_code == 0, result.stdout


# ---- lub list ---------------------------------------------------------------


def test_list_all_shows_estimators_and_backends() -> None:
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "Estimators" in result.stdout
    assert "Backends" in result.stdout
    assert "token_logprob" in result.stdout
    assert "dummy" in result.stdout


def test_list_estimators_only() -> None:
    result = runner.invoke(app, ["list", "estimators"])
    assert result.exit_code == 0
    assert "Estimators" in result.stdout
    assert "Backends" not in result.stdout
    assert "semantic_entropy" in result.stdout


def test_list_datasets() -> None:
    result = runner.invoke(app, ["list", "datasets"])
    assert result.exit_code == 0
    assert "Datasets" in result.stdout
    assert "br_regulatory" in result.stdout


def test_list_regimes() -> None:
    result = runner.invoke(app, ["list", "regimes"])
    assert result.exit_code == 0
    assert "Regulatory regimes" in result.stdout


def test_list_unknown_component() -> None:
    result = runner.invoke(app, ["list", "foobar"])
    assert result.exit_code != 0


# ---- lub scan ---------------------------------------------------------------


def test_scan_json_output(tmp_path: Path) -> None:
    out_dir = tmp_path / "results"
    bench = runner.invoke(
        app,
        [
            "benchmark",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", "token_logprob",
            "--dataset", "br_regulatory",
            "--limit", "3",
            "--out", str(out_dir),
        ],
    )
    assert bench.exit_code == 0

    scan_result = runner.invoke(
        app,
        ["scan", "--input", str(out_dir), "--format", "json"],
    )
    assert scan_result.exit_code == 0
    parsed = json.loads(scan_result.stdout)
    assert isinstance(parsed, list)
    assert len(parsed) >= 1
    assert "passed" in parsed[0]


def test_scan_md_output(tmp_path: Path) -> None:
    from tests import make_benchmark_result

    result_file = tmp_path / "result.json"
    result_file.write_text(make_benchmark_result().model_dump_json(), encoding="utf-8")
    scan_result = runner.invoke(
        app,
        ["scan", "--input", str(result_file), "--format", "md"],
    )
    assert scan_result.exit_code == 0
    assert "Vulnerability" in scan_result.stdout


def test_scan_missing_input() -> None:
    result = runner.invoke(app, ["scan", "--input", "/nonexistent/path"])
    assert result.exit_code == 1


# ---- lub drift --------------------------------------------------------------


def test_drift_refuses_result_files(tmp_path: Path) -> None:
    """Valid result files still fail closed: they persist only aggregate
    metrics, and a PSI verdict fabricated from those has no meaning."""
    from tests import make_benchmark_result

    ref_file = tmp_path / "ref.json"
    cur_file = tmp_path / "cur.json"
    ref_file.write_text(
        make_benchmark_result(accuracy=0.75, ece=0.08).model_dump_json(),
        encoding="utf-8",
    )
    cur_file.write_text(
        make_benchmark_result(accuracy=0.70, ece=0.12).model_dump_json(),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["drift", "--reference", str(ref_file), "--current", str(cur_file)],
    )
    assert result.exit_code == 1
    out = result.stdout or ""
    try:
        out += result.stderr or ""
    except (ValueError, AttributeError):
        pass
    assert "aggregate" in out


def test_drift_missing_file() -> None:
    result = runner.invoke(
        app,
        ["drift", "--reference", "/ghost/a.json", "--current", "/ghost/b.json"],
    )
    assert result.exit_code == 1
