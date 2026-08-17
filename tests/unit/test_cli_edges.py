# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""CLI edge-case tests — verbose/quiet flags, corrupt input files,
report parse failures."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from lub.cli import app

runner = CliRunner(mix_stderr=False)


def test_verbose_flag_accepted() -> None:
    result = runner.invoke(
        app,
        [
            "--verbose",
            "answer",
            "q",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", "token_logprob",
        ],
    )
    assert result.exit_code == 0


def test_quiet_flag_accepted() -> None:
    result = runner.invoke(
        app,
        [
            "--quiet",
            "answer",
            "q",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", "token_logprob",
        ],
    )
    assert result.exit_code == 0


def test_verbose_and_quiet_together_rejected() -> None:
    result = runner.invoke(
        app,
        ["--verbose", "--quiet", "answer", "q", "--model", "d", "--backend", "dummy"],
    )
    assert result.exit_code == 1


def test_answer_rejects_unknown_backend() -> None:
    result = runner.invoke(
        app,
        [
            "answer",
            "q",
            "--model", "d",
            "--backend", "not-a-real-backend",
            "--estimator", "token_logprob",
        ],
    )
    assert result.exit_code == 1
    assert "unknown backend" in result.stderr.lower()


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


def test_report_rejects_corrupt_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    out = tmp_path / "report.md"
    result = runner.invoke(
        app,
        ["report", "--input", str(bad), "--format", "md", "--out", str(out)],
    )
    assert result.exit_code == 1
    assert "parse" in result.stderr.lower()


def test_report_empty_directory(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    out = tmp_path / "report.md"
    result = runner.invoke(
        app,
        ["report", "--input", str(empty), "--format", "md", "--out", str(out)],
    )
    assert result.exit_code == 1
    assert "no json" in result.stderr.lower()


def test_repro_rejects_corrupt_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    result = runner.invoke(app, ["repro", str(bad)])
    assert result.exit_code == 1
    assert "parse" in result.stderr.lower()


def test_config_rejects_invalid_toml(tmp_path: Path) -> None:
    p = tmp_path / "cfg.toml"
    p.write_text("this is not [valid toml", encoding="utf-8")
    result = runner.invoke(app, ["benchmark", "--config", str(p)])
    assert result.exit_code != 0
