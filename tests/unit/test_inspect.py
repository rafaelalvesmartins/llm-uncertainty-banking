# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for ``lub.cli.inspect`` commands: list, scan, drift, repro."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from lub.cli import app

# ---------- fixtures ----------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


@pytest.fixture
def mock_result() -> MagicMock:
    r = MagicMock()
    r.backend = "openai:gpt-4"
    r.estimator = "logprob"
    r.dataset = "boolq"
    r.dataset_hash = "hash_abc"
    r.n = 10
    r.seed = 42
    r.accuracy = 0.85
    r.ece = 0.05
    r.refusal_auroc = 0.78
    r.metrics = {"0": 0.9, "1": 0.7, "2": 0.8}
    return r


@pytest.fixture
def results_file(tmp_path: Path) -> Path:
    p = tmp_path / "results.json"
    p.write_text("{}", encoding="utf-8")
    return p


def _combined(result) -> str:
    """Return stdout + stderr (whichever the typer version exposes)."""
    parts = [result.stdout or ""]
    try:
        parts.append(result.stderr or "")
    except (ValueError, AttributeError):
        pass
    return "\n".join(parts)


# ---------- list ----------


def test_list_estimators(runner: CliRunner) -> None:
    with patch("lub.uncertainty.base.list_estimators", return_value=["entropy", "mc_dropout"]):
        result = runner.invoke(app, ["list", "estimators"])
    assert result.exit_code == 0
    assert "Estimators" in result.stdout
    assert "entropy" in result.stdout
    assert "mc_dropout" in result.stdout


def test_list_backends(runner: CliRunner) -> None:
    with patch("lub.wrappers.base.list_backends", return_value=["openai", "anthropic"]):
        result = runner.invoke(app, ["list", "backends"])
    assert result.exit_code == 0
    assert "Backends" in result.stdout
    assert "openai" in result.stdout


def test_list_datasets(runner: CliRunner) -> None:
    with patch(
        "lub.benchmarks.base.Dataset.list_datasets", return_value=["boolq", "triviaqa"]
    ):
        result = runner.invoke(app, ["list", "datasets"])
    assert result.exit_code == 0
    assert "Datasets" in result.stdout
    assert "boolq" in result.stdout


def test_list_all_aggregates_sections(runner: CliRunner) -> None:
    with patch(
        "lub.uncertainty.base.list_estimators", return_value=["entropy"]
    ), patch("lub.wrappers.base.list_backends", return_value=["openai"]), patch(
        "lub.benchmarks.base.Dataset.list_datasets", return_value=["boolq"]
    ), patch(
        "lub.reports.crosswalk.regimes", return_value=["bcb_4893"]
    ), patch(
        "lub.mcp.server.list_all_tools",
        return_value=[type("FakeTool", (), {"name": "scan"})()],
    ):
        result = runner.invoke(app, ["list", "all"])
    assert result.exit_code == 0
    for section in ("Estimators", "Backends", "Datasets"):
        assert section in result.stdout


def test_list_unknown_component(runner: CliRunner) -> None:
    result = runner.invoke(app, ["list", "bogus"])
    assert result.exit_code != 0
    assert "unknown component" in _combined(result).lower()


# ---------- scan ----------


def test_scan_input_not_found(runner: CliRunner, tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    result = runner.invoke(app, ["scan", "--input", str(missing)])
    assert result.exit_code != 0
    assert "does not exist" in _combined(result)


def test_scan_no_json_files(runner: CliRunner, tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    result = runner.invoke(app, ["scan", "--input", str(empty_dir)])
    assert result.exit_code != 0
    assert "no JSON" in _combined(result)


def test_scan_parse_failure(runner: CliRunner, results_file: Path) -> None:
    with patch(
        "lub.types.BenchmarkResult.model_validate_json",
        side_effect=ValueError("bad json"),
    ):
        result = runner.invoke(app, ["scan", "--input", str(results_file)])
    assert result.exit_code != 0
    assert "failed to parse" in _combined(result)


def test_scan_json_output_to_stdout(
    runner: CliRunner, results_file: Path, mock_result: MagicMock
) -> None:
    fake_report = MagicMock()
    fake_report.to_dict = lambda: {"backend": "openai", "passed": True, "issues": []}
    with patch(
        "lub.types.BenchmarkResult.model_validate_json", return_value=mock_result
    ), patch(
        "lub.reports.giskard_report.scan_benchmark_result", return_value=fake_report
    ):
        result = runner.invoke(
            app, ["scan", "--input", str(results_file), "--format", "json"]
        )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, list)
    assert parsed[0]["passed"] is True


def test_scan_md_output(
    runner: CliRunner, results_file: Path, mock_result: MagicMock
) -> None:
    fake_report = MagicMock()
    fake_report.backend = "openai:gpt-4"
    fake_report.estimator = "logprob"
    fake_report.worst_severity = "low"
    fake_report.passed = True
    fake_report.issues = []
    with patch(
        "lub.types.BenchmarkResult.model_validate_json", return_value=mock_result
    ), patch(
        "lub.reports.giskard_report.scan_benchmark_result", return_value=fake_report
    ):
        result = runner.invoke(
            app, ["scan", "--input", str(results_file), "--format", "md"]
        )
    assert result.exit_code == 0
    assert "# Vulnerability Scan Results" in result.stdout
    assert "openai:gpt-4" in result.stdout
    assert "logprob" in result.stdout


def test_scan_bad_format(
    runner: CliRunner, results_file: Path, mock_result: MagicMock
) -> None:
    fake_report = MagicMock()
    fake_report.to_dict = lambda: {}
    with patch(
        "lub.types.BenchmarkResult.model_validate_json", return_value=mock_result
    ), patch(
        "lub.reports.giskard_report.scan_benchmark_result", return_value=fake_report
    ):
        result = runner.invoke(
            app, ["scan", "--input", str(results_file), "--format", "xml"]
        )
    assert result.exit_code != 0
    assert "format must be" in _combined(result)


def test_scan_writes_output_file(
    runner: CliRunner, results_file: Path, mock_result: MagicMock, tmp_path: Path
) -> None:
    out = tmp_path / "nested" / "out.json"
    fake_report = MagicMock()
    fake_report.to_dict = lambda: {"passed": True}
    with patch(
        "lub.types.BenchmarkResult.model_validate_json", return_value=mock_result
    ), patch(
        "lub.reports.giskard_report.scan_benchmark_result", return_value=fake_report
    ):
        result = runner.invoke(
            app, ["scan", "--input", str(results_file), "--out", str(out)]
        )
    assert result.exit_code == 0
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data[0]["passed"] is True


def test_scan_directory_input_collects_all_jsons(
    runner: CliRunner, tmp_path: Path, mock_result: MagicMock
) -> None:
    d = tmp_path / "results"
    d.mkdir()
    (d / "a.json").write_text("{}", encoding="utf-8")
    (d / "b.json").write_text("{}", encoding="utf-8")
    fake_report = MagicMock()
    fake_report.to_dict = lambda: {"passed": True}
    with patch(
        "lub.types.BenchmarkResult.model_validate_json", return_value=mock_result
    ), patch(
        "lub.reports.giskard_report.scan_benchmark_result", return_value=fake_report
    ):
        result = runner.invoke(app, ["scan", "--input", str(d), "--format", "json"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert len(parsed) == 2


# ---------- drift ----------


def test_drift_missing_reference(
    runner: CliRunner, tmp_path: Path, results_file: Path
) -> None:
    missing = tmp_path / "missing.json"
    result = runner.invoke(
        app,
        ["drift", "--reference", str(missing), "--current", str(results_file)],
    )
    assert result.exit_code != 0
    out = _combined(result).lower()
    assert "reference" in out and "not found" in out


def test_drift_missing_current(
    runner: CliRunner, tmp_path: Path, results_file: Path
) -> None:
    missing = tmp_path / "missing.json"
    result = runner.invoke(
        app,
        ["drift", "--reference", str(results_file), "--current", str(missing)],
    )
    assert result.exit_code != 0
    out = _combined(result).lower()
    assert "current" in out and "not found" in out


def test_drift_parse_failure(runner: CliRunner, results_file: Path) -> None:
    with patch(
        "lub.types.BenchmarkResult.model_validate_json", side_effect=ValueError("bad")
    ):
        result = runner.invoke(
            app,
            ["drift", "--reference", str(results_file), "--current", str(results_file)],
        )
    assert result.exit_code != 0
    assert "failed to parse" in _combined(result)


def test_drift_refuses_aggregate_only_result_files(
    runner: CliRunner, results_file: Path, mock_result: MagicMock
) -> None:
    """Result files persist aggregate metrics, not per-example confidences;
    a PSI/CBPE verdict fabricated from them must be refused, not printed."""
    with patch(
        "lub.types.BenchmarkResult.model_validate_json", return_value=mock_result
    ), patch("lub.calibration.drift.analyze_drift") as analyze:
        result = runner.invoke(
            app,
            ["drift", "--reference", str(results_file), "--current", str(results_file)],
        )
    assert result.exit_code != 0
    out = _combined(result)
    assert "aggregate" in out and "per-example" in out
    analyze.assert_not_called()


# ---------- repro ----------


def test_repro_file_not_found(runner: CliRunner, tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    result = runner.invoke(app, ["repro", str(missing)])
    assert result.exit_code != 0
    assert "file not found" in _combined(result).lower()


def test_repro_parse_failure(runner: CliRunner, results_file: Path) -> None:
    with patch(
        "lub.types.BenchmarkResult.model_validate_json", side_effect=ValueError("bad")
    ):
        result = runner.invoke(app, ["repro", str(results_file)])
    assert result.exit_code != 0
    assert "failed to parse" in _combined(result)


def test_repro_build_failure_reports_user_error(
    runner: CliRunner, results_file: Path, mock_result: MagicMock
) -> None:
    with patch(
        "lub.types.BenchmarkResult.model_validate_json", return_value=mock_result
    ), patch(
        "lub.wrappers.base.ModelBackend.resolve_class_name", return_value="openai"
    ), patch(
        "lub.pipeline.UncertaintyPipeline.from_pretrained",
        side_effect=ValueError("unknown estimator"),
    ):
        result = runner.invoke(app, ["repro", str(results_file)])
    assert result.exit_code != 0
    assert "unknown estimator" in _combined(result)


def test_repro_match_exits_zero(
    runner: CliRunner, results_file: Path, mock_result: MagicMock
) -> None:
    replayed = MagicMock()
    replayed.accuracy = 0.85
    replayed.ece = 0.05
    replayed.refusal_auroc = 0.78
    replayed.dataset_hash = "hash_abc"  # matches mock_result

    fake_runner = MagicMock()
    fake_runner.run.return_value = replayed

    with patch(
        "lub.types.BenchmarkResult.model_validate_json", return_value=mock_result
    ), patch(
        "lub.wrappers.base.ModelBackend.resolve_class_name", return_value="openai"
    ), patch(
        "lub.pipeline.UncertaintyPipeline.from_pretrained", return_value=MagicMock()
    ), patch(
        "lub.cli.benchmark._resolve_dataset", return_value=MagicMock()
    ), patch(
        "lub.benchmarks.runner.BenchmarkRunner", return_value=fake_runner
    ), patch(
        "lub.benchmarks.runner.content_hash", return_value="same_hash"
    ):
        result = runner.invoke(app, ["repro", str(results_file)])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["hash_match"] is True
    assert payload["diffs"] == {}
    assert payload["original_dataset_hash"] == payload["replayed_dataset_hash"]


def test_repro_metric_mismatch_exits_nonzero(
    runner: CliRunner, results_file: Path, mock_result: MagicMock
) -> None:
    replayed = MagicMock()
    replayed.accuracy = 0.70  # diverges by 0.15 -- well beyond default tolerance
    replayed.ece = 0.05
    replayed.refusal_auroc = 0.78
    replayed.dataset_hash = "hash_abc"

    fake_runner = MagicMock()
    fake_runner.run.return_value = replayed

    with patch(
        "lub.types.BenchmarkResult.model_validate_json", return_value=mock_result
    ), patch(
        "lub.wrappers.base.ModelBackend.resolve_class_name", return_value="openai"
    ), patch(
        "lub.pipeline.UncertaintyPipeline.from_pretrained", return_value=MagicMock()
    ), patch(
        "lub.cli.benchmark._resolve_dataset", return_value=MagicMock()
    ), patch(
        "lub.benchmarks.runner.BenchmarkRunner", return_value=fake_runner
    ), patch(
        "lub.benchmarks.runner.content_hash", side_effect=["h_original", "h_replayed"]
    ):
        result = runner.invoke(app, ["repro", str(results_file)])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["hash_match"] is False
    assert "accuracy" in payload["diffs"]
    assert payload["diffs"]["accuracy"]["original"] == 0.85
    assert payload["diffs"]["accuracy"]["replayed"] == 0.70


def test_repro_dataset_hash_mismatch_exits_nonzero(
    runner: CliRunner, results_file: Path, mock_result: MagicMock
) -> None:
    """Metrics match but dataset_hash differs -- must still exit non-zero."""
    replayed = MagicMock()
    replayed.accuracy = 0.85
    replayed.ece = 0.05
    replayed.refusal_auroc = 0.78
    replayed.dataset_hash = "hash_DIFFERENT"

    fake_runner = MagicMock()
    fake_runner.run.return_value = replayed

    with patch(
        "lub.types.BenchmarkResult.model_validate_json", return_value=mock_result
    ), patch(
        "lub.wrappers.base.ModelBackend.resolve_class_name", return_value="openai"
    ), patch(
        "lub.pipeline.UncertaintyPipeline.from_pretrained", return_value=MagicMock()
    ), patch(
        "lub.cli.benchmark._resolve_dataset", return_value=MagicMock()
    ), patch(
        "lub.benchmarks.runner.BenchmarkRunner", return_value=fake_runner
    ), patch(
        "lub.benchmarks.runner.content_hash", return_value="same"
    ):
        result = runner.invoke(app, ["repro", str(results_file)])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["diffs"] == {}
    assert payload["original_dataset_hash"] != payload["replayed_dataset_hash"]


def test_repro_backend_without_separator(
    runner: CliRunner, results_file: Path, mock_result: MagicMock
) -> None:
    """backend without ':' should be treated as model_id only."""
    mock_result.backend = "gpt-4-only"  # no ':' separator
    replayed = MagicMock()
    replayed.accuracy = 0.85
    replayed.ece = 0.05
    replayed.refusal_auroc = 0.78
    replayed.dataset_hash = "hash_abc"
    fake_runner = MagicMock()
    fake_runner.run.return_value = replayed

    with patch(
        "lub.types.BenchmarkResult.model_validate_json", return_value=mock_result
    ), patch(
        "lub.wrappers.base.ModelBackend.resolve_class_name", return_value="openai"
    ) as resolve, patch(
        "lub.pipeline.UncertaintyPipeline.from_pretrained", return_value=MagicMock()
    ) as from_pretrained, patch(
        "lub.cli.benchmark._resolve_dataset", return_value=MagicMock()
    ), patch(
        "lub.benchmarks.runner.BenchmarkRunner", return_value=fake_runner
    ), patch(
        "lub.benchmarks.runner.content_hash", return_value="h"
    ):
        result = runner.invoke(app, ["repro", str(results_file)])
    assert result.exit_code == 0
    # backend_name passed to resolver should be the empty partition prefix
    resolve.assert_called_once_with("gpt-4-only")
    # model_id falls through to the full backend string
    _, kwargs = from_pretrained.call_args
    assert kwargs["model"] == "gpt-4-only"


def test_repro_runner_exception_is_internal_error(
    runner: CliRunner, results_file: Path, mock_result: MagicMock
) -> None:
    fake_runner = MagicMock()
    fake_runner.run.side_effect = RuntimeError("backend timeout")

    with patch(
        "lub.types.BenchmarkResult.model_validate_json", return_value=mock_result
    ), patch(
        "lub.wrappers.base.ModelBackend.resolve_class_name", return_value="openai"
    ), patch(
        "lub.pipeline.UncertaintyPipeline.from_pretrained", return_value=MagicMock()
    ), patch(
        "lub.cli.benchmark._resolve_dataset", return_value=MagicMock()
    ), patch(
        "lub.benchmarks.runner.BenchmarkRunner", return_value=fake_runner
    ):
        result = runner.invoke(app, ["repro", str(results_file)])
    assert result.exit_code != 0


def test_repro_custom_tolerance_suppresses_small_diff(
    runner: CliRunner, results_file: Path, mock_result: MagicMock
) -> None:
    """A diff smaller than --tolerance should not appear in the diff payload."""
    replayed = MagicMock()
    replayed.accuracy = 0.85001  # diff of 1e-5, below tolerance 1e-3
    replayed.ece = 0.05
    replayed.refusal_auroc = 0.78
    replayed.dataset_hash = "hash_abc"

    fake_runner = MagicMock()
    fake_runner.run.return_value = replayed

    with patch(
        "lub.types.BenchmarkResult.model_validate_json", return_value=mock_result
    ), patch(
        "lub.wrappers.base.ModelBackend.resolve_class_name", return_value="openai"
    ), patch(
        "lub.pipeline.UncertaintyPipeline.from_pretrained", return_value=MagicMock()
    ), patch(
        "lub.cli.benchmark._resolve_dataset", return_value=MagicMock()
    ), patch(
        "lub.benchmarks.runner.BenchmarkRunner", return_value=fake_runner
    ), patch(
        "lub.benchmarks.runner.content_hash", return_value="same"
    ):
        result = runner.invoke(
            app, ["repro", str(results_file), "--tolerance", "1e-3"]
        )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["diffs"] == {}
