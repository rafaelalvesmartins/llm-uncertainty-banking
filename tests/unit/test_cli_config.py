# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""CLI --config tests."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from lub.cli import app

runner = CliRunner(mix_stderr=False)


def _write_config(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "cfg.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_benchmark_loads_config_file(tmp_path: Path) -> None:
    out_dir = tmp_path / "results"
    cfg = _write_config(
        tmp_path,
        f'''
        model = "dummy-0"
        backend = "dummy"
        estimator = "token_logprob"
        dataset = "br_regulatory"
        limit = 3
        seed = 0
        out = "{out_dir.as_posix()}"
        ''',
    )
    result = runner.invoke(app, ["benchmark", "--config", str(cfg)])
    assert result.exit_code == 0, result.stderr
    assert list(out_dir.glob("*.json"))


def test_cli_flag_overrides_config(tmp_path: Path) -> None:
    out_dir = tmp_path / "results"
    cfg = _write_config(
        tmp_path,
        f'''
        model = "dummy-0"
        backend = "dummy"
        estimator = "token_logprob"
        dataset = "br_regulatory"
        limit = 20
        out = "{out_dir.as_posix()}"
        ''',
    )
    result = runner.invoke(
        app,
        ["benchmark", "--config", str(cfg), "--limit", "2"],
    )
    assert result.exit_code == 0, result.stderr
    import json
    written = next(out_dir.glob("*.json"))
    record = json.loads(written.read_text(encoding="utf-8"))
    assert record["n"] == 2


def test_config_rejects_unknown_keys(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        '''
        model = "dummy-0"
        backend = "dummy"
        estimator = "token_logprob"
        dataset = "br_regulatory"
        not_a_real_key = "foo"
        ''',
    )
    result = runner.invoke(app, ["benchmark", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "unknown config keys" in result.stderr.lower()


def test_config_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["benchmark", "--config", str(tmp_path / "nope.toml")]
    )
    assert result.exit_code == 1


def test_benchmark_without_config_requires_flags() -> None:
    result = runner.invoke(app, ["benchmark"])
    assert result.exit_code == 1
    assert "missing required" in result.stderr.lower()
