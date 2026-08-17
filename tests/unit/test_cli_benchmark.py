# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Unit tests for :mod:`lub.cli.benchmark`.

Covers the two private helpers (``_load_benchmark_config`` and
``_resolve_dataset``) and the public ``benchmark`` Typer command. All
tests invoke through ``CliRunner`` against the in-process ``DummyBackend``
so no network, weights, or external state is required.
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest
import typer
from typer.testing import CliRunner

from lub.benchmarks.base import Dataset
from lub.cli import EXIT_INTERNAL, EXIT_USER, app
from lub.cli.benchmark import _load_benchmark_config, _resolve_dataset

runner = CliRunner(mix_stderr=False)


@pytest.fixture(autouse=True)
def _eager_load_datasets() -> None:
    """Ensure the ``br_regulatory`` dataset is registered for each test.

    Triggers the lazy-registry import path. Conftest preserves keys listed
    in :data:`lub.benchmarks.base._LAZY_REGISTRY` across tests, so this is
    a fast no-op after the first load. We deliberately avoid manipulating
    ``sys.modules``: popping and re-importing would create a fresh module
    object and invalidate aliases held elsewhere (notably
    ``lub.domains.banking.br_regulatory``).
    """
    from lub.benchmarks.base import Dataset

    Dataset.get_dataset_cls("br_regulatory")


def _extract_json(text: str) -> dict:
    """Return the last balanced top-level JSON object in ``text``.

    Mirrors the helper in ``test_cli.py``: structlog may interleave info
    lines on stdout in CI when stderr is captured separately, so the
    parser walks brace depth and returns the final complete object.
    """
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
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


# ---------------------------------------------------------------------------
# _load_benchmark_config
# ---------------------------------------------------------------------------


def test_load_benchmark_config_returns_dict(tmp_path: Path) -> None:
    """A well-formed TOML file with allowed keys should parse to a dict."""
    cfg = tmp_path / "bench.toml"
    cfg.write_text(
        dedent(
            """
            model = "dummy-0"
            backend = "dummy"
            estimator = "token_logprob"
            dataset = "br_regulatory"
            limit = 3
            seed = 42
            out = "out/results"
            """
        ).strip(),
        encoding="utf-8",
    )
    data = _load_benchmark_config(cfg)
    assert data["model"] == "dummy-0"
    assert data["backend"] == "dummy"
    assert data["limit"] == 3
    assert data["seed"] == 42


def test_load_benchmark_config_rejects_missing_file(tmp_path: Path) -> None:
    """Missing config files should raise ``typer.BadParameter``."""
    with pytest.raises(typer.BadParameter, match="config file not found"):
        _load_benchmark_config(tmp_path / "does-not-exist.toml")


def test_load_benchmark_config_rejects_unknown_keys(tmp_path: Path) -> None:
    """Unknown TOML keys must surface as a ``BadParameter`` error."""
    cfg = tmp_path / "bench.toml"
    cfg.write_text('model = "x"\nbogus = "nope"\n', encoding="utf-8")
    with pytest.raises(typer.BadParameter, match="unknown config keys"):
        _load_benchmark_config(cfg)


def test_load_benchmark_config_accepts_partial_config(tmp_path: Path) -> None:
    """Only a subset of allowed keys may be present in the file."""
    cfg = tmp_path / "bench.toml"
    cfg.write_text('model = "dummy-0"\n', encoding="utf-8")
    data = _load_benchmark_config(cfg)
    assert data == {"model": "dummy-0"}


# ---------------------------------------------------------------------------
# _resolve_dataset
# ---------------------------------------------------------------------------


def test_resolve_dataset_returns_dataset_instance() -> None:
    """A registered dataset key should produce a concrete ``Dataset``."""
    ds = _resolve_dataset("br_regulatory")
    assert isinstance(ds, Dataset)


def test_resolve_dataset_unknown_raises_bad_parameter() -> None:
    """An unknown dataset key should surface as ``typer.BadParameter``."""
    with pytest.raises(typer.BadParameter):
        _resolve_dataset("definitely-not-a-real-dataset")


# ---------------------------------------------------------------------------
# benchmark command — CLI path
# ---------------------------------------------------------------------------


def test_benchmark_cli_writes_result_json(tmp_path: Path) -> None:
    """End-to-end: a successful run echoes JSON and persists a file."""
    out_dir = tmp_path / "results"
    result = runner.invoke(
        app,
        [
            "benchmark",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", "token_logprob",
            "--dataset", "br_regulatory",
            "--limit", "2",
            "--out", str(out_dir),
            "--seed", "0",
        ],
    )
    assert result.exit_code == 0, result.stdout
    parsed = _extract_json(result.stdout)
    assert parsed["n"] == 2
    assert parsed["dataset"] == "br_regulatory"
    files = list(out_dir.glob("*.json"))
    assert files, "benchmark runner should persist at least one result JSON"


def test_benchmark_cli_missing_required_args_exits_user() -> None:
    """Missing model + dataset must exit with EXIT_USER and a clear error."""
    result = runner.invoke(app, ["benchmark", "--backend", "dummy"])
    assert result.exit_code == EXIT_USER
    assert "missing required args" in result.stderr.lower()


def test_benchmark_cli_unknown_dataset_exits_user() -> None:
    """An unknown ``--dataset`` should exit with the user-error code."""
    result = runner.invoke(
        app,
        [
            "benchmark",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", "token_logprob",
            "--dataset", "no-such-dataset",
        ],
    )
    assert result.exit_code == EXIT_USER


def test_benchmark_cli_unknown_estimator_exits_user() -> None:
    """An unknown estimator should be surfaced as user error via pipeline."""
    result = runner.invoke(
        app,
        [
            "benchmark",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", "not-a-real-estimator",
            "--dataset", "br_regulatory",
            "--limit", "1",
        ],
    )
    assert result.exit_code == EXIT_USER


def test_benchmark_cli_uses_config_file(tmp_path: Path) -> None:
    """Values may be sourced entirely from a TOML config."""
    out_dir = tmp_path / "results"
    cfg = tmp_path / "bench.toml"
    cfg.write_text(
        dedent(
            f"""
            model = "dummy-0"
            backend = "dummy"
            estimator = "token_logprob"
            dataset = "br_regulatory"
            limit = 2
            seed = 0
            out = "{out_dir.as_posix()}"
            """
        ).strip(),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["benchmark", "--config", str(cfg)])
    assert result.exit_code == 0, result.stdout
    assert list(out_dir.glob("*.json"))


def test_benchmark_cli_flags_override_config(tmp_path: Path) -> None:
    """CLI flags must take precedence over the TOML config values."""
    cfg_out = tmp_path / "from_config"
    cli_out = tmp_path / "from_cli"
    cfg = tmp_path / "bench.toml"
    cfg.write_text(
        dedent(
            f"""
            model = "dummy-0"
            backend = "dummy"
            estimator = "token_logprob"
            dataset = "br_regulatory"
            limit = 5
            seed = 0
            out = "{cfg_out.as_posix()}"
            """
        ).strip(),
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "benchmark",
            "--config", str(cfg),
            "--limit", "1",
            "--out", str(cli_out),
        ],
    )
    assert result.exit_code == 0, result.stdout
    # CLI --out wins; the config directory must not be created/populated.
    assert list(cli_out.glob("*.json"))
    assert not cfg_out.exists() or not list(cfg_out.glob("*.json"))
    # The echoed record should reflect the overridden --limit=1.
    parsed = _extract_json(result.stdout)
    assert parsed["n"] == 1


def test_benchmark_cli_bad_config_file_exits_user(tmp_path: Path) -> None:
    """A bad ``--config`` path must produce EXIT_USER, not crash."""
    result = runner.invoke(app, ["benchmark", "--config", str(tmp_path / "ghost.toml")])
    assert result.exit_code == EXIT_USER
    assert "config file not found" in result.stderr.lower()


def test_benchmark_cli_unknown_config_keys_exits_user(tmp_path: Path) -> None:
    """Unknown TOML keys must produce EXIT_USER with a clear message."""
    cfg = tmp_path / "bench.toml"
    cfg.write_text('model = "dummy-0"\nbogus = true\n', encoding="utf-8")
    result = runner.invoke(app, ["benchmark", "--config", str(cfg)])
    assert result.exit_code == EXIT_USER
    assert "unknown config keys" in result.stderr.lower()


# ---------------------------------------------------------------------------
# benchmark command — internal-error path
# ---------------------------------------------------------------------------


def test_benchmark_cli_runner_runtime_error_exits_internal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``RuntimeError`` from the runner should surface as EXIT_INTERNAL."""
    from lub.benchmarks.runner import BenchmarkRunner

    def _boom(self, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated runner failure")

    monkeypatch.setattr(BenchmarkRunner, "run", _boom)

    result = runner.invoke(
        app,
        [
            "benchmark",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", "token_logprob",
            "--dataset", "br_regulatory",
            "--limit", "1",
            "--out", str(tmp_path / "results"),
        ],
    )
    assert result.exit_code == EXIT_INTERNAL


def test_benchmark_cli_runner_value_error_exits_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``ValueError`` from the runner should surface as EXIT_USER."""
    from lub.benchmarks.runner import BenchmarkRunner

    def _boom(self, **_kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("invalid runner argument")

    monkeypatch.setattr(BenchmarkRunner, "run", _boom)

    result = runner.invoke(
        app,
        [
            "benchmark",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", "token_logprob",
            "--dataset", "br_regulatory",
            "--limit", "1",
            "--out", str(tmp_path / "results"),
        ],
    )
    assert result.exit_code == EXIT_USER
    assert "invalid runner argument" in result.stderr.lower()


# ---------------------------------------------------------------------------
# The CLI must let you pick the correctness scorer (it was hard-wired to exact_match)
# ---------------------------------------------------------------------------


def test_cli_can_select_the_fuzzy_correctness_scorer(tmp_path: Path, monkeypatch) -> None:
    """Regression: ``BenchmarkRunner`` takes a pluggable ``correctness_fn`` and the library
    ships ``fuzzy_match`` for verbose LLM completions — but ``lub benchmark`` built the runner
    without it, so EVERY CLI run scored with strict ``exact_match``.

    On a verbose free-text answer that is factually right, exact_match says WRONG, which
    understates accuracy AND corrupts every calibration metric computed against those labels.
    (It is why a bespoke script had to be written to produce the one real benchmark number.)
    """
    from lub.benchmarks.correctness import fuzzy_match
    from lub.benchmarks.runner import BenchmarkRunner

    captured: dict[str, object] = {}
    real_init = BenchmarkRunner.__init__

    def spy_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured["correctness_fn"] = kwargs.get("correctness_fn")
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(BenchmarkRunner, "__init__", spy_init)

    result = runner.invoke(
        app,
        [
            "benchmark",
            "--model", "dummy-0",
            "--backend", "dummy",
            "--estimator", "token_logprob",
            "--dataset", "br_regulatory",
            "--limit", "2",
            "--correctness", "fuzzy_match",
            "--out", str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["correctness_fn"] is fuzzy_match, (
        "`lub benchmark --correctness fuzzy_match` did not reach the runner "
        f"(got {captured['correctness_fn']!r}) — the CLI is still hard-wired to exact_match"
    )


def test_benchmark_config_accepts_a_correctness_key(tmp_path: Path) -> None:
    """The scorer must also be settable from a config file, like every other run parameter."""
    cfg = tmp_path / "bench.toml"
    cfg.write_text('model = "x"\ncorrectness = "fuzzy_match"\n', encoding="utf-8")
    data = _load_benchmark_config(cfg)
    assert data["correctness"] == "fuzzy_match"
